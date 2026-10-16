"""Azure HTTP helpers, cost, metrics, status, and log reports with mocked I/O."""
from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.providers import azure_cli, azure_estate, azure_infra
from app.providers.azure_infra import AzureCredentials


def _creds() -> AzureCredentials:
    return AzureCredentials("tenant", "client", "secret", "sub-1")


def _json_response(payload: dict, status: int = 200) -> MagicMock:
    resp = MagicMock(status_code=status, text=str(payload)[:200])
    resp.json.return_value = payload
    return resp


@pytest.mark.unit
def test_error_detail_parses_nested_and_plain_errors():
    nested = _json_response(
        {"error": {"details": [{"message": "Reader role missing"}], "message": "fail"}}
    )
    assert "Reader" in azure_infra._error_detail(nested)
    simple = _json_response({"error_description": "invalid_client\nmore"})
    assert azure_infra._error_detail(simple) == "invalid_client"
    code = _json_response({"error": "throttled"})
    assert "throttled" in azure_infra._error_detail(code)
    dict_err = _json_response({"error": {"message": "denied"}})
    assert "denied" in azure_infra._error_detail(dict_err)
    broken = MagicMock(status_code=500, text="not-json")
    broken.json.side_effect = ValueError("bad")
    assert azure_infra._error_detail(broken) == "not-json"


@pytest.mark.unit
def test_get_token_success_empty_and_http_errors():
    creds = _creds()
    ok = _json_response({"access_token": "tok"})
    with patch("app.providers.azure_infra.httpx.post", return_value=ok):
        assert azure_infra._get_token(creds) == "tok"
    denied = _json_response({"error": "invalid_client"}, status=401)
    with patch("app.providers.azure_infra.httpx.post", return_value=denied):
        with pytest.raises(azure_infra.AzureApiError, match="authentication failed"):
            azure_infra._get_token(creds)
    with patch(
        "app.providers.azure_infra.httpx.post",
        side_effect=httpx.ConnectError("down"),
    ):
        with pytest.raises(azure_infra.AzureApiError, match="Could not reach"):
            azure_infra._get_token(creds)


@pytest.mark.unit
def test_run_query_success_and_failure():
    ok = _json_response({"data": [{"name": "rg1"}]})
    with patch("app.providers.azure_infra.httpx.post", return_value=ok):
        rows = azure_infra._run_query("tok", ["sub-1"], "Resources")
    assert rows[0]["name"] == "rg1"
    bad = _json_response({"error": {"message": "denied"}}, status=403)
    with patch("app.providers.azure_infra.httpx.post", return_value=bad):
        with pytest.raises(azure_infra.AzureApiError, match="query failed"):
            azure_infra._run_query("tok", [], "Resources")
    with patch(
        "app.providers.azure_infra.httpx.post",
        side_effect=httpx.ReadTimeout("slow"),
    ):
        with pytest.raises(azure_infra.AzureApiError, match="request failed"):
            azure_infra._run_query("tok", ["sub-1"], "Resources")


@pytest.mark.unit
def test_build_cost_report_filters_and_missing_subscription():
    missing_sub = AzureCredentials("t", "c", "s", None)
    with patch("app.providers.azure_infra.load_credentials", return_value=missing_sub):
        with pytest.raises(azure_infra.AzureApiError, match="subscription"):
            azure_infra.build_cost_report("p1", date(2026, 7, 1), date(2026, 7, 31), "July")
    cost = _json_response(
        {
            "properties": {
                "columns": [
                    {"name": "Cost"},
                    {"name": "ServiceName"},
                    {"name": "Meter"},
                    {"name": "Currency"},
                ],
                "rows": [
                    [12.5, "Storage", "LRS", "USD"],
                    [3.0, "Compute", "VM", "USD"],
                    [1.0, "Azure OpenAI", "Tokens", "USD"],
                ],
            }
        }
    )
    with patch("app.providers.azure_infra.load_credentials", return_value=_creds()):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra.httpx.post", return_value=cost):
                report = azure_infra.build_cost_report(
                    "p1",
                    date(2026, 7, 1),
                    date(2026, 7, 31),
                    "July",
                    group_by="meter",
                    service_filter=["storage"],
                )
    assert report["meta"]["subscription"] == "sub-1"
    assert "Storage" in report["text"]
    assert "Compute" not in report["text"]


@pytest.mark.unit
def test_build_metrics_report_plots_container_app_cpu():
    resource = {
        "name": "app1",
        "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/app1",
        "type": "microsoft.app/containerapps",
        "cpuAlloc": 0.5,
        "memAlloc": "1Gi",
    }
    defs = [
        {
            "name": {"value": "UsageNanoCores", "localizedValue": "CPU Usage"},
            "primaryAggregationType": "Average",
            "unit": "NanoCores",
        }
    ]
    payload = {
        "value": [
            {
                "timeseries": [
                    {
                        "data": [
                            {"timeStamp": "t1", "average": 1e8},
                            {"timeStamp": "t2", "average": 2e8},
                        ]
                    }
                ]
            }
        ]
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=_creds()):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[resource]):
                with patch("app.providers.azure_infra._fetch_metric_definitions", return_value=defs):
                    with patch("app.providers.azure_infra._fetch_metric", return_value=payload):
                        report = azure_infra.build_metrics_report(
                            "p1", "cpu last 24 hours", metric_hints=["cpu"]
                        )
    assert report["charts"]
    assert "app1" in report["text"]


@pytest.mark.unit
def test_build_status_report_counts_http_errors():
    resource = {
        "name": "app1",
        "id": "/subscriptions/s/resourceGroups/rg/providers/Microsoft.App/containerApps/app1",
        "type": "microsoft.app/containerapps",
    }
    payload = {
        "value": [
            {
                "timeseries": [
                    {
                        "metadatavalues": [
                            {"name": {"value": "statusCode"}, "value": "500"}
                        ],
                        "data": [{"timeStamp": "t1", "total": 4}],
                    },
                    {
                        "metadatavalues": [
                            {"name": {"value": "statusCode"}, "value": "200"}
                        ],
                        "data": [{"timeStamp": "t1", "total": 10}],
                    },
                ]
            }
        ]
    }
    with patch("app.providers.azure_infra.load_credentials", return_value=_creds()):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._discover_resources", return_value=[resource]):
                with patch("app.providers.azure_infra._fetch_metric_split", return_value=payload):
                    report = azure_infra.build_status_report("p1", "how many 500 errors last hour")
    assert "500=4" in report["text"]
    assert report["charts"]


@pytest.mark.unit
def test_build_logs_report_requires_workspace():
    with patch("app.providers.azure_infra.load_credentials", return_value=_creds()):
        with patch("app.providers.azure_infra._get_token", return_value="tok"):
            with patch("app.providers.azure_infra._log_workspaces", return_value=[]):
                with patch("app.providers.azure_infra._run_query", return_value=[]):
                    with pytest.raises(azure_infra.AzureApiError, match="Log Analytics"):
                        azure_infra.build_logs_report("p1", "show me the errors")


@pytest.mark.unit
def test_arm_get_and_metric_fetch_failures():
    bad = _json_response({"error": "no"}, status=404)
    with patch("app.providers.azure_infra.httpx.get", return_value=bad):
        with pytest.raises(azure_infra.AzureApiError):
            azure_infra._arm_get("tok", "/subscriptions/s", "2021-04-01")
        with pytest.raises(azure_infra.AzureApiError):
            azure_infra._fetch_metric(
                "tok",
                "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Web/sites/app",
                "CpuPercentage",
                "Average",
                datetime(2026, 8, 15, tzinfo=timezone.utc),
                datetime(2026, 8, 15, 1, tzinfo=timezone.utc),
                "PT1H",
            )
    with patch("app.providers.azure_infra.httpx.get", side_effect=httpx.ConnectError("x")):
        assert azure_infra._fetch_metric_definitions("tok", "/id") == []


@pytest.mark.unit
def test_parse_status_targets_and_log_timespan():
    codes, cats, errors = azure_infra._parse_status_targets("show 400 and 5xx errors")
    assert "400" in codes
    assert "5xx" in cats
    assert errors is True
    span = azure_infra._log_timespan(
        datetime(2026, 8, 1, tzinfo=timezone.utc),
        datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert "2026-08-01" in span
    assert azure_infra._fmt_log_rows(["Time", "Msg"], [["t", "boom"]])
    assert azure_infra._fmt_log_rows(["Time"], []) == "(none)"


_SUBSCRIPTION = "11111111-1111-4111-8111-111111111111"
_CONNECTION = "a" * 32


@pytest.mark.unit
def test_fold_costs_matches_the_october_fixture():
    days = azure_estate.each_day("2026-10-01", "2026-10-04")
    folded = azure_estate.fold_costs(
        [
            {"UsageDate": 20261001, "ServiceName": "Virtual Machines", "Cost": 10, "Currency": "USD"},
            {"UsageDate": 20261003, "ServiceName": "Virtual Machines", "Cost": 5, "Currency": "USD"},
        ],
        days,
    )
    assert len(folded["points"]) == 3
    assert folded["points"][1]["spend"] == 0
    assert folded["total"] == 15


@pytest.mark.unit
def test_operator_estate_does_not_send_a_cost_body():
    azure_estate.clear_estate_cache()
    calls: list[list[str]] = []

    def runner(profile, args, **_kwargs):
        calls.append(list(args))
        return []

    model = azure_estate.load_estate(
        org_id="org-1",
        project={"id": "proj-1", "name": "Estate", "budget_usd": None},
        range_id="mtd",
        can_see_cost=False,
        fresh=True,
        runner=runner,
        prepare=lambda *_args, **_kwargs: None,
        subscriptions=[
            {
                "id": _SUBSCRIPTION,
                "name": "Sub",
                "state": "Enabled",
                "connection_id": _CONNECTION,
            }
        ],
    )
    blob = " ".join(" ".join(args) for args in calls)
    assert "CostManagement" not in blob
    assert "2023-11-01" not in blob
    assert any(args[:2] == ["resource", "list"] for args in calls)
    assert model["canSeeCost"] is False
    assert model["kpis"]["spend"] is None
    assert _SUBSCRIPTION in blob
    assert "other-subscription" not in blob


@pytest.mark.unit
def test_allowlist_names_the_fifteen_read_tokens():
    assert azure_cli.ALLOWED == {
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


@pytest.mark.unit
def test_profile_refresh_uses_the_token_and_strips_host_env(tmp_path, monkeypatch):
    monkeypatch.setattr(
        azure_cli,
        "_get_token_payload",
        lambda creds, scope="https://management.azure.com/.default": {
            "access_token": "token-value",
            "expires_in": 3600,
        },
    )
    profile = tmp_path / "profile"
    azure_cli.ensure_profile(profile, AzureCredentials("tenant", "client", "secret-value"))
    stored = (profile / "accessTokens.json").read_text(encoding="utf-8")
    assert "token-value" in stored
    assert "secret-value" not in stored
    env = azure_cli.child_env(profile, {"AZURE_CLIENT_SECRET": "secret-value", "PATH": "/usr/bin"})
    assert "AZURE_CLIENT_SECRET" not in env
    assert env["AZURE_CONFIG_DIR"] == str(profile)
    redacted = azure_cli.redact("Bearer abc secret-value\nline", "secret-value")
    assert "Bearer [redacted]" in redacted
    assert "secret-value" not in redacted
    assert "\n" not in redacted
    assert len(azure_cli.redact("x" * 900)) == 700
