"""Role-based access control for InfraLens.

Hierarchy (highest privilege first):
  super_admin > org_admin > devops_lead > devops_engineer > developer > viewer
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request

ROLE_ORDER: tuple[str, ...] = (
    "viewer",
    "developer",
    "devops_engineer",
    "devops_lead",
    "org_admin",
    "super_admin",
)

ROLE_LABELS: dict[str, str] = {
    "super_admin": "Super Admin",
    "org_admin": "Org Admin",
    "devops_lead": "DevOps Lead",
    "devops_engineer": "DevOps Engineer",
    "developer": "Developer",
    "viewer": "Viewer",
}

CAPABILITY_MIN_ROLE: dict[str, str] = {
    "read": "viewer",
    "chat": "developer",
    "propose_write": "developer",
    "create_project": "developer",
    "connect_provider": "developer",
    "create_github_repo": "developer",
    "approve_human": "devops_engineer",
    "run_workflow": "devops_engineer",
    "run_architecture": "devops_lead",
    "verify_memory": "devops_engineer",
    "archive_memory": "devops_lead",
    "approve_two_person": "devops_lead",
    "prod_apply": "devops_lead",
    "prod_revert": "org_admin",
    "break_glass": "devops_lead",
    "manage_users": "org_admin",
    "invite_users": "org_admin",
    "approve_membership": "org_admin",
    "manage_org": "org_admin",
    "create_org": "super_admin",
    "delete_project": "org_admin",
    "system_settings": "super_admin",
}

GATE_MIN_ROLE: dict[str, str] = {
    "autonomous": "developer",
    "autonomous_logged": "developer",
    "auto_instant_undo": "developer",
    "auto_apply": "devops_engineer",
    "human_approval": "devops_engineer",
    "two_person": "devops_lead",
}

# Live org and project roles. They are not suite ladder rungs.
LIVE_ORG_ROLES: tuple[str, ...] = ("org_owner", "org_admin", "member")
LIVE_PROJECT_ROLES: tuple[str, ...] = (
    "project_admin",
    "billing_reader",
    "operator",
    "viewer",
)
LIVE_ROLE_LABELS: dict[str, str] = {
    "org_owner": "Organization owner",
    "org_admin": "Organization admin",
    "member": "Member",
    "project_admin": "Project admin",
    "billing_reader": "Billing reader",
    "operator": "Operator",
    "viewer": "Viewer",
}
_LIVE_ONLY_ROLES = frozenset(
    {"org_owner", "member", "project_admin", "billing_reader", "operator"}
)
_ORG_ONLY_PERMISSIONS = frozenset(
    {"connection.manage", "members.manage", "project.create"}
)
_PROJECT_PERMISSIONS: dict[str, tuple[str, ...]] = {
    "project_admin": ("project.read", "billing.read", "resources.read", "project.manage"),
    "billing_reader": ("project.read", "billing.read", "resources.read"),
    "operator": ("project.read", "resources.read"),
    "viewer": ("project.read", "billing.read", "resources.read"),
}
_ROLE_ALIASES = {
    "admin": "super_admin",
    "superadmin": "super_admin",
    "orgadmin": "org_admin",
    "lead": "devops_lead",
    "engineer": "devops_engineer",
    "dev": "developer",
    "readonly": "viewer",
    "read_only": "viewer",
}


def _raw_role(role: Optional[str]) -> str:
    return (role or "").strip().lower().replace(" ", "_").replace("-", "_")


def normalize_role(role: Optional[str]) -> str:
    value = _ROLE_ALIASES.get(_raw_role(role or "developer"), _raw_role(role or "developer"))
    return value if value in ROLE_LABELS else "developer"


def presented_role(role: Optional[str]) -> str:
    """Role stored on a session payload.

    ``normalize_role`` maps unknown names, including live ``operator``, to
    developer. Capability checks must still see the live name.
    """
    raw = _ROLE_ALIASES.get(_raw_role(role), _raw_role(role))
    if raw in _LIVE_ONLY_ROLES or raw in ROLE_LABELS:
        return raw
    return normalize_role(role)


def suite_role(user: dict[str, Any]) -> str:
    """Suite rung used for capability checks.

    A live role such as ``operator`` is not passed through ``normalize_role``,
    so the developer default cannot grant writes or billing. ``org_owner``
    receives org-admin powers and does not become ``super_admin``.
    """
    raw = _ROLE_ALIASES.get(_raw_role(str(user.get("role") or "")), _raw_role(str(user.get("role") or "")))
    if raw in _LIVE_ONLY_ROLES:
        base = "viewer"
    elif raw in ROLE_LABELS:
        base = raw
    else:
        base = "developer"
    if base == "super_admin":
        return base
    org_role = _raw_role(str(user.get("org_role") or ""))
    if org_role in {"org_owner", "org_admin"} and role_rank(base) < role_rank("org_admin"):
        return "org_admin"
    return base


def is_org_manager(role: Optional[str]) -> bool:
    return _raw_role(role) in {"org_owner", "org_admin"}


def live_can(
    org_role: Optional[str],
    project_role: Optional[str],
    permission: str,
) -> bool:
    """Live permission. Operator cannot read billing. Viewer can. No project role fails."""
    if permission in _ORG_ONLY_PERMISSIONS:
        return is_org_manager(org_role)
    if is_org_manager(org_role):
        return True
    if not project_role:
        return False
    return permission in _PROJECT_PERMISSIONS.get(_raw_role(project_role), ())


def role_label(role: Optional[str]) -> str:
    """Live labels, then the suite labels. Viewer is the same word on both."""
    key = _raw_role(role)
    if key in LIVE_ROLE_LABELS and key != "viewer":
        return LIVE_ROLE_LABELS[key]
    if key in ROLE_LABELS:
        return ROLE_LABELS[key]
    return ROLE_LABELS.get(normalize_role(role), "Developer")


def role_rank(role: Optional[str]) -> int:
    try:
        return ROLE_ORDER.index(normalize_role(role))
    except ValueError:
        return 0


def has_min_role(user_role: Optional[str], minimum: str) -> bool:
    return role_rank(user_role) >= role_rank(minimum)


def can(user: dict[str, Any], capability: str) -> bool:
    minimum = CAPABILITY_MIN_ROLE.get(capability, "super_admin")
    return has_min_role(suite_role(user), minimum)


def can_approve_gate(user: dict[str, Any], gate: str) -> bool:
    minimum = GATE_MIN_ROLE.get(gate, "devops_lead")
    return has_min_role(user.get("role"), minimum)


def _current_user(
    request: Request,
    authorization: Optional[str] = Header(default=None),
) -> dict[str, Any]:
    from app.core import auth

    return auth.require_user(request, authorization)


def require_capability(capability: str):
    """FastAPI dependency factory: require a capability for the current user."""

    def _dep(user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
        if not can(user, capability):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {ROLE_LABELS.get(CAPABILITY_MIN_ROLE.get(capability, ''), 'higher')} role or above",
            )
        return user

    return _dep


def require_min_role(minimum: str):
    def _dep(user: dict[str, Any] = Depends(_current_user)) -> dict[str, Any]:
        if not has_min_role(user.get("role"), minimum):
            raise HTTPException(
                status_code=403,
                detail=f"Requires {ROLE_LABELS.get(normalize_role(minimum), minimum)} role or above",
            )
        return user

    return _dep


def assert_capability(user: dict[str, Any], capability: str) -> None:
    if not can(user, capability):
        raise HTTPException(
            status_code=403,
            detail=f"Requires {ROLE_LABELS.get(CAPABILITY_MIN_ROLE.get(capability, ''), 'higher')} role or above",
        )


def public_roles() -> list[dict[str, str]]:
    return [{"id": key, "label": label} for key, label in ROLE_LABELS.items()]
