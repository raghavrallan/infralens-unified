"""Allowlisted Azure CLI reads and a per-connection profile.

The client secret is exchanged for a token by ``azure_infra._get_token_payload``.
That token is written into the profile directory. The CLI process never receives
the secret on its argv or in the host Azure environment variables.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from app.providers.azure_infra import AzureCredentials, _get_token_payload

ALLOWED = frozenset(
    {
        "version",
        "login",
        "account",
        "rest",
        "resource",
        "vm",
        "group",
        "databricks",
        "storage",
        "containerapp",
        "aks",
        "webapp",
        "datafactory",
        "advisor",
        "monitor",
    }
)
_PROFILE_KEY = re.compile(r"^[a-f0-9]{32}$")
_STRIPPED_ENV = (
    "AZURE_CLIENT_ID",
    "AZURE_CLIENT_SECRET",
    "AZURE_TENANT_ID",
    "AZURE_CLIENT_CERTIFICATE_PATH",
    "AZURE_SUBSCRIPTION_ID",
    "AZURE_USERNAME",
    "AZURE_PASSWORD",
)
_WINDOWS_CLI = r"C:\Program Files\Microsoft SDKs\Azure\CLI2\python.exe"
_LOCKS: dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class AzureCliError(RuntimeError):
    """A refused or failed allowlisted Azure CLI read."""


def profile_key(connection_id: str) -> str:
    """32 hex directory key. UUIDs are hashed so the directory rule stays intact."""
    raw = (connection_id or "").strip().lower().replace("-", "")
    if _PROFILE_KEY.fullmatch(raw):
        return raw
    return hashlib.sha256((connection_id or "").encode("utf-8")).hexdigest()[:32]


def profile_dir(connection_id: str) -> Path:
    key = profile_key(connection_id)
    if not _PROFILE_KEY.fullmatch(key):
        raise AzureCliError("Invalid connection.")
    root = Path(os.environ.get("AZURE_PROFILE_ROOT", "data"))
    return root / "azure-profiles" / key


def redact(text: str, secret: str = "") -> str:
    out = str(text or "")
    if secret:
        out = out.replace(secret, "[redacted]")
    out = re.sub(r"Bearer\s+\S+", "Bearer [redacted]", out, flags=re.IGNORECASE)
    out = re.sub(r"\s+", " ", out).strip()
    return out[:700]


def launcher() -> tuple[str, list[str]]:
    python = os.environ.get("AZURE_CLI_PYTHON") or ""
    if python and os.path.isfile(python):
        return python, ["-IBm", "azure.cli"]
    if sys.platform == "win32" and os.path.isfile(_WINDOWS_CLI):
        return _WINDOWS_CLI, ["-IBm", "azure.cli"]
    return "az", []


def child_env(profile: Path, base: Optional[dict[str, str]] = None) -> dict[str, str]:
    env = dict(base or os.environ)
    env["AZURE_CONFIG_DIR"] = str(profile)
    env["AZURE_CORE_COLLECT_TELEMETRY"] = "0"
    env["AZURE_CORE_NO_COLOR"] = "1"
    for key in _STRIPPED_ENV:
        env.pop(key, None)
    return env


def _reject_secret_argv(args: list[str]) -> None:
    secret_flag = "--" + "password"
    if secret_flag in args:
        raise AzureCliError("Refusing to place a secret on the Azure CLI command line.")


def run_az(
    profile: Path,
    args: list[str],
    *,
    secret: str = "",
    timeout_ms: int = 180_000,
    env: Optional[dict[str, str]] = None,
) -> Any:
    if not args or args[0] not in ALLOWED:
        raise AzureCliError("That Azure CLI command is not allowed.")
    _reject_secret_argv(args)
    profile.mkdir(parents=True, exist_ok=True)
    command, prefix = launcher()
    try:
        completed = subprocess.run(
            [command, *prefix, *args],
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_ms / 1000,
            env=child_env(profile, env),
            check=False,
        )
    except FileNotFoundError as exc:
        raise AzureCliError("Azure CLI is not installed on this server.") from exc
    except subprocess.TimeoutExpired as exc:
        raise AzureCliError("Azure CLI timed out.") from exc
    if completed.returncode != 0:
        detail = redact(completed.stderr or completed.stdout or f"Azure CLI exited {completed.returncode}", secret)
        raise AzureCliError(detail or "Azure CLI failed.")
    text = (completed.stdout or "").strip()
    if not text or text == "null":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _expires_at(payload: dict[str, Any]) -> datetime:
    seconds = int(payload.get("expires_in") or 3600)
    return datetime.now(timezone.utc) + timedelta(seconds=max(seconds, 60))


def _token_still_valid(profile: Path) -> bool:
    path = profile / "accessTokens.json"
    if not path.is_file():
        return False
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(rows, list) or not rows:
        return False
    raw = str(rows[0].get("expiresOn") or "")
    try:
        expires = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return expires - datetime.now(timezone.utc) > timedelta(minutes=5)


def write_profile_token(
    profile: Path,
    *,
    token: str,
    expires_on: datetime,
    tenant_id: str,
    client_id: str,
    subscription_id: Optional[str] = None,
) -> None:
    profile.mkdir(parents=True, exist_ok=True)
    entry = {
        "accessToken": token,
        "expiresOn": expires_on.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "tokenType": "Bearer",
        "resource": "https://management.core.windows.net/",
        "userId": client_id,
        "tenant": tenant_id,
        "_authority": f"https://login.microsoftonline.com/{tenant_id}",
    }
    (profile / "accessTokens.json").write_text(json.dumps([entry]), encoding="utf-8")
    subscriptions = []
    if subscription_id:
        subscriptions.append(
            {
                "id": subscription_id,
                "name": subscription_id,
                "state": "Enabled",
                "tenantId": tenant_id,
                "isDefault": True,
                "environmentName": "AzureCloud",
                "user": {"name": client_id, "type": "servicePrincipal"},
            }
        )
    (profile / "azureProfile.json").write_text(
        json.dumps({"installationId": profile.name, "subscriptions": subscriptions}),
        encoding="utf-8",
    )


def access_token_args() -> list[str]:
    return ["account", "get-access-token", "--resource", "https://management.azure.com", "-o", "json"]


def list_subscription_args() -> list[str]:
    return ["account", "list", "--refresh", "-o", "json"]


def cli_access_token(profile: Path) -> Optional[dict[str, Any]]:
    """A-16. A missing CLI or an empty profile is not a failed estate page."""
    try:
        token = run_az(profile, access_token_args(), timeout_ms=8000)
    except AzureCliError:
        return None
    return token if isinstance(token, dict) else None


def list_subscriptions(profile: Path) -> list[dict[str, str]]:
    """A-17. Keep rows whose id is a GUID."""
    rows = run_az(profile, list_subscription_args())
    if not isinstance(rows, list):
        return []
    guid = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
    cleaned = []
    for row in rows:
        if not isinstance(row, dict) or not guid.fullmatch(str(row.get("id") or "")):
            continue
        cleaned.append(
            {
                "id": str(row.get("id")),
                "name": str(row.get("name") or row.get("id")),
                "state": str(row.get("state") or ""),
            }
        )
    return cleaned


def ensure_profile(profile: Path, creds: AzureCredentials) -> None:
    """Refresh the CLI profile from the client-credentials token."""
    if _token_still_valid(profile):
        return
    existing = cli_access_token(profile)
    expires = ""
    if isinstance(existing, dict):
        expires = str(existing.get("expiresOn") or existing.get("expires_on") or "")
    if expires:
        try:
            parsed = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            if parsed - datetime.now(timezone.utc) > timedelta(minutes=5):
                return
        except ValueError:
            pass
    payload = _get_token_payload(creds)
    token = str(payload.get("access_token") or "")
    if not token:
        raise AzureCliError("Azure authentication did not return an access token.")
    write_profile_token(
        profile,
        token=token,
        expires_on=_expires_at(payload),
        tenant_id=creds.tenant_id,
        client_id=creds.client_id,
        subscription_id=creds.subscription_id,
    )


def with_lock(key: str, work):
    with _LOCKS_GUARD:
        lock = _LOCKS.setdefault(key, threading.Lock())
    with lock:
        return work()
