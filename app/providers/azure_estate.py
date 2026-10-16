"""Estate read model ported from infralens-live.

Successes are cached for 90 seconds. Failures are not cached. Cost queries are
omitted when the caller cannot see billing. Subscription ids come only from
``subscriptions_for_project``.
"""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from app.providers.azure_cli import (
    AzureCliError,
    profile_dir,
    redact,
    run_az,
    with_lock,
)
from app.providers.azure_infra import AzureCredentials
from app.tenancy.access import connection_secrets, subscriptions_for_project

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_TTL_SECONDS = 90.0
_COLORS = [
    "#E2773C", "#C45E28", "#F2A365", "#0084FF", "#0BAA60",
    "#7C6AE8", "#232323", "#0E7490", "#D4537E", "#717171",
]
_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
RANGES = (
    {"id": "7d", "label": "Last 7 days", "spendLabel": "7-day spend"},
    {"id": "30d", "label": "Last 30 days", "spendLabel": "30-day spend"},
    {"id": "mtd", "label": "This month", "spendLabel": "Month spend"},
    {"id": "qtr", "label": "This quarter", "spendLabel": "Quarter spend"},
)
Runner = Callable[..., Any]


def range_by_id(range_id: Optional[str]) -> dict[str, str]:
    for item in RANGES:
        if item["id"] == range_id:
            return dict(item)
    return dict(RANGES[2])


def range_window(range_id: str, now: Optional[datetime] = None) -> dict[str, str]:
    moment = now or datetime.now(timezone.utc)
    end = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc) + timedelta(days=1)
    if range_id == "7d":
        start = end - timedelta(days=7)
    elif range_id == "30d":
        start = end - timedelta(days=30)
    elif range_id == "qtr":
        start = datetime(moment.year, (moment.month - 1) // 3 * 3 + 1, 1, tzinfo=timezone.utc)
    else:
        start = datetime(moment.year, moment.month, 1, tzinfo=timezone.utc)
    return {"from": start.date().isoformat(), "to": end.date().isoformat()}


def each_day(start: str, end: str) -> list[str]:
    cursor = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    stop = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    days: list[str] = []
    while cursor < stop:
        days.append(cursor.strftime("%Y%m%d"))
        cursor += timedelta(days=1)
    return days


def day_key(value: Any) -> str:
    raw = "" if value is None else str(value)
    return raw if re.fullmatch(r"\d{8}", raw) else ""


def label_from_key(key: str) -> str:
    month = _MONTHS[int(key[4:6]) - 1] if key[4:6].isdigit() else ""
    return f"{int(key[6:8])} {month}".strip()


def _round(value: float) -> float:
    return int(value * 100 + (0.5 if value >= 0 else -0.5)) / 100


def _amount(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    if math.isnan(number) or math.isinf(number):
        return 0.0
    return number


def _cost_of(row: dict[str, Any]) -> float:
    for key in ("Cost", "PreTaxCost", "cost", "totalCost"):
        if row.get(key) is not None:
            return _amount(row.get(key))
    return 0.0


def rows_of(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    props = payload.get("properties") if isinstance(payload.get("properties"), dict) else payload
    columns = props.get("columns") or []
    rows = props.get("rows") or []
    shaped: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for index, column in enumerate(columns):
            name = column.get("name") if isinstance(column, dict) else str(column)
            item[str(name)] = row[index] if index < len(row) else None
        shaped.append(item)
    return shaped


def fold_costs(service_rows: list[dict[str, Any]], days: list[str]) -> dict[str, Any]:
    by_day = {key: 0.0 for key in days}
    by_service: dict[str, float] = {}
    currency = "USD"
    for row in service_rows:
        key = day_key(row.get("UsageDate") or row.get("BillingDate") or row.get("Date"))
        cost = _cost_of(row)
        if row.get("Currency") or row.get("BillingCurrency"):
            currency = str(row.get("Currency") or row.get("BillingCurrency"))
        if key in by_day:
            by_day[key] += cost
        name = str(row.get("ServiceName") or row.get("MeterCategory") or "Other")
        by_service[name] = by_service.get(name, 0.0) + cost
    points = [{"label": label_from_key(key), "spend": _round(by_day.get(key) or 0)} for key in days]
    ranked = sorted(
        ({"name": name, "cost": _round(cost)} for name, cost in by_service.items()),
        key=lambda item: item["cost"],
        reverse=True,
    )
    ranked = [item for item in ranked if item["cost"] != 0]
    services = [
        {**item, "color": _COLORS[index % len(_COLORS)]}
        for index, item in enumerate(ranked[:8])
    ]
    rest = sum(item["cost"] for item in ranked[8:])
    if rest > 0:
        services.append({"name": "Other", "cost": _round(rest), "color": "#717171"})
    total = _round(sum(by_day.values()))
    return {"currency": currency, "points": points, "services": services, "total": total}


def fold_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, float] = {}
    for row in rows:
        name = str(row.get("ResourceGroupName") or row.get("ResourceGroup") or "Ungrouped")
        grouped[name] = grouped.get(name, 0.0) + _cost_of(row)
    items = [
        {"name": name, "cost": _round(cost), "color": _COLORS[index % len(_COLORS)]}
        for index, (name, cost) in enumerate(grouped.items())
    ]
    items = [item for item in items if item["cost"] != 0]
    items.sort(key=lambda item: item["cost"], reverse=True)
    return items[:8]


def fold_meters(rows: list[dict[str, Any]], days: list[str]) -> dict[str, Any]:
    totals: dict[str, float] = {}
    for row in rows:
        name = str(row.get("Meter") or row.get("MeterName") or row.get("MeterSubCategory") or "Usage")
        totals[name] = totals.get(name, 0.0) + _amount(row.get("UsageQuantity") if row.get("UsageQuantity") is not None else row.get("qty") if row.get("qty") is not None else row.get("Quantity"))
    chosen = sorted(((name, qty) for name, qty in totals.items() if qty != 0), key=lambda item: item[1], reverse=True)[:4]
    series = [
        {"key": f"m{index}", "name": name, "color": _COLORS[index % len(_COLORS)]}
        for index, (name, _qty) in enumerate(chosen)
    ]
    keys = {name: f"m{index}" for index, (name, _qty) in enumerate(chosen)}
    table = {key: {"day": label_from_key(key)} for key in days}
    for point in table.values():
        for item in series:
            point[item["key"]] = 0
    for row in rows:
        slot = table.get(day_key(row.get("UsageDate") or row.get("Date")))
        series_key = keys.get(str(row.get("Meter") or row.get("MeterName") or row.get("MeterSubCategory") or "Usage"))
        if not slot or not series_key:
            continue
        slot[series_key] = _round(slot[series_key] + _amount(row.get("UsageQuantity") if row.get("UsageQuantity") is not None else row.get("qty") if row.get("qty") is not None else row.get("Quantity")))
    return {"series": series, "points": [table[key] for key in days]}


def forecast_month(total: float, elapsed_days: int, now: Optional[datetime] = None) -> Optional[float]:
    if not elapsed_days:
        return None
    moment = now or datetime.now(timezone.utc)
    if moment.month == 12:
        nxt = datetime(moment.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        nxt = datetime(moment.year, moment.month + 1, 1, tzinfo=timezone.utc)
    days_in_month = (nxt - timedelta(days=1)).day
    return _round((total / elapsed_days) * days_in_month)


def cost_body(start: str, end: str, grouping: str, filt: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    aggregation = (
        {"qty": {"name": "UsageQuantity", "function": "Sum"}}
        if grouping == "Meter"
        else {"totalCost": {"name": "Cost", "function": "Sum"}}
    )
    body: dict[str, Any] = {
        "type": "ActualCost",
        "timeframe": "Custom",
        "timePeriod": {"from": f"{start}T00:00:00Z", "to": f"{end}T00:00:00Z"},
        "dataset": {
            "granularity": "Daily",
            "aggregation": aggregation,
            "grouping": [{"type": "Dimension", "name": grouping}],
        },
    }
    if filt:
        body["dataset"]["filter"] = filt
    return body


def clear_estate_cache() -> None:
    _CACHE.clear()


def _cache_get(key: str) -> Optional[dict[str, Any]]:
    hit = _CACHE.get(key)
    if not hit:
        return None
    if time.monotonic() - hit[0] > _TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    return hit[1]


def _power_label(value: Any) -> str:
    text = str(value or "Unknown")
    if re.search(r"running", text, re.IGNORECASE):
        return "Running"
    if re.search(r"deallocated|stopped", text, re.IGNORECASE):
        return "Stopped"
    return re.sub(r"^VM\s+", "", text, flags=re.IGNORECASE)


def resource_kind(resource: dict[str, Any]) -> str:
    kind_type = str(resource.get("type") or "").lower()
    kind = str(resource.get("kind") or "").lower()
    if "microsoft.compute/virtualmachines" in kind_type:
        return "vm"
    if "microsoft.storage/storageaccounts" in kind_type:
        return "storage"
    if "microsoft.cdn" in kind_type:
        return "cdn"
    if any(token in kind_type for token in ("microsoft.sql", "microsoft.documentdb", "microsoft.dbfor", "microsoft.cache")):
        return "database"
    if "function" in kind or "microsoft.logic" in kind_type:
        return "serverless"
    return "other"


def _safe(warnings: list[str], label: str, work) -> Any:
    try:
        return work()
    except Exception as exc:  # noqa: BLE001 - one failed read must not blank the page
        warnings.append(redact(f"{label}: {exc}"))
        return None


def _scoped(command: list[str], subscription_id: str) -> list[str]:
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", subscription_id, re.IGNORECASE):
        raise AzureCliError("Invalid subscription.")
    return [*command, "--subscription", subscription_id]


def _read_subscription(runner: Runner, profile, subscription: dict[str, Any], window: dict[str, str], can_see_cost: bool, warnings: list[str]) -> dict[str, Any]:
    sub_id = str(subscription["id"])
    name = str(subscription.get("name") or sub_id)

    def read(label: str, args: list[str]) -> Any:
        return _safe(warnings, f"{name} {label}", lambda: runner(profile, _scoped(args, sub_id)))

    resources = read("resources", ["resource", "list"]) or []
    vms = read("virtual machines", ["vm", "list", "-d"]) or []
    groups = read("resource groups", ["group", "list"]) or []
    workspaces = read("Databricks", ["databricks", "workspace", "list"]) or []
    storage = read("storage", ["storage", "account", "list"]) or []
    apps = read("container apps", ["containerapp", "list"]) or []
    clusters = read("Kubernetes", ["aks", "list"]) or []
    sites = read("app service", ["webapp", "list"]) or []
    factories = read("data factories", ["datafactory", "list"]) or []
    advisor = read("advisor", ["advisor", "recommendation", "list"]) or []
    activity = read("activity", ["monitor", "activity-log", "list", "--offset", "7d"]) or []
    alerts = read("alerts", ["monitor", "metrics", "alert", "list"]) or []
    service_cost = group_cost = meter_cost = None
    if can_see_cost:
        service_cost = _safe(
            warnings,
            f"{name} service cost",
            lambda: runner(profile, ["rest", "--method", "post", "--url", _cost_url(sub_id), "--body", json.dumps(cost_body(window["from"], window["to"], "ServiceName")), "-o", "json"]),
        )
        group_cost = _safe(
            warnings,
            f"{name} resource group cost",
            lambda: runner(profile, ["rest", "--method", "post", "--url", _cost_url(sub_id), "--body", json.dumps(cost_body(window["from"], window["to"], "ResourceGroupName")), "-o", "json"]),
        )
        meter_filter = {"dimensions": {"name": "ServiceName", "operator": "In", "values": ["Azure Databricks"]}}
        meter_cost = _safe(
            warnings,
            f"{name} Databricks usage",
            lambda: runner(profile, ["rest", "--method", "post", "--url", _cost_url(sub_id), "--body", json.dumps(cost_body(window["from"], window["to"], "Meter", meter_filter)), "-o", "json"]),
        )
    return {
        "resources": resources,
        "vms": vms,
        "groups": groups,
        "workspaces": workspaces,
        "storage": storage,
        "apps": apps,
        "clusters": clusters,
        "sites": sites,
        "factories": factories,
        "advisor": advisor,
        "activity": activity,
        "alerts": alerts,
        "serviceRows": rows_of(service_cost),
        "groupRows": rows_of(group_cost),
        "meterRows": rows_of(meter_cost),
    }


def _cost_url(subscription_id: str) -> str:
    return (
        "https://management.azure.com/subscriptions/"
        f"{subscription_id}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    )


def _empty(project: dict[str, Any], range_info: dict[str, str], can_see_cost: bool, subscriptions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "setup",
        "message": "",
        "warnings": [],
        "canSeeCost": can_see_cost,
        "range": range_info,
        "project": {
            "id": project.get("id"),
            "name": project.get("name"),
            "budget": project.get("budget_usd"),
        },
        "subscriptions": [
            {"id": item.get("id"), "name": item.get("name"), "state": item.get("state")}
            for item in subscriptions
        ],
        "kpis": {
            "spend": None,
            "currency": "USD",
            "forecast": None,
            "resourceCount": 0,
            "vmCount": 0,
            "vmRunning": 0,
            "groupCount": 0,
        },
        "trend": {"title": f"Spend · {range_info['label'].lower()}", "points": []},
        "services": [],
        "groups": [],
        "databricks": {"series": [], "points": []},
        "vms": [],
        "hosting": [],
        "workspaces": [],
        "storage": [],
        "pipelines": [],
        "resources": [],
        "activity": [],
        "alerts": [],
        "advisor": [],
        "syncedAt": int(time.time() * 1000),
    }


def load_estate(
    *,
    org_id: str,
    project: dict[str, Any],
    range_id: str,
    can_see_cost: bool,
    fresh: bool = False,
    runner: Optional[Runner] = None,
    prepare: Optional[Callable[..., None]] = None,
    subscriptions: Optional[list[dict[str, Any]]] = None,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    range_info = range_by_id(range_id)
    window = range_window(range_info["id"], now)
    rows = subscriptions if subscriptions is not None else subscriptions_for_project(str(project.get("id") or ""), org_id)
    base = _empty(project, range_info, can_see_cost, rows)
    if not rows:
        base["message"] = "Map an Azure connection to this project."
        return base
    key = f"{org_id}:{project.get('id')}:{range_info['id']}:{can_see_cost}:{','.join(str(item.get('id')) for item in rows)}"
    if not fresh:
        cached = _cache_get(key)
        if cached is not None:
            return dict(cached)
    warnings: list[str] = []
    chunks: list[dict[str, Any]] = []
    by_connection: dict[str, list[dict[str, Any]]] = {}
    for subscription in rows:
        by_connection.setdefault(str(subscription.get("connection_id") or ""), []).append(subscription)
    read = runner or run_az
    for connection_id, group in by_connection.items():
        def _read_group(connection_id: str = connection_id, group: list[dict[str, Any]] = group) -> None:
            creds = None
            try:
                if prepare is not None:
                    prepare(profile_dir(connection_id), connection_id, org_id)
                else:
                    secrets = connection_secrets(connection_id, org_id)
                    creds = AzureCredentials(
                        tenant_id=secrets["tenant_id"],
                        client_id=secrets["client_id"],
                        client_secret=secrets["client_secret"],
                    )
                    from app.providers.azure_cli import ensure_profile

                    ensure_profile(profile_dir(connection_id), creds)
            except Exception as exc:  # noqa: BLE001 - surface a warning, do not invent inventory
                warnings.append(redact(str(exc), getattr(creds, "client_secret", "") if creds else ""))
                return
            finally:
                if creds is not None:
                    creds.client_secret = ""
            for subscription in group:
                chunks.append(_read_subscription(read, profile_dir(connection_id), subscription, window, can_see_cost, warnings))

        with_lock(connection_id or "none", _read_group)
    days = each_day(window["from"], window["to"])
    costs = (
        fold_costs([row for chunk in chunks for row in chunk["serviceRows"]], days)
        if can_see_cost
        else {"currency": "USD", "points": [], "services": [], "total": 0}
    )
    groups = fold_groups([row for chunk in chunks for row in chunk["groupRows"]]) if can_see_cost else []
    databricks = (
        fold_meters([row for chunk in chunks for row in chunk["meterRows"]], days)
        if can_see_cost
        else {"series": [], "points": []}
    )
    resources = []
    for chunk in chunks:
        for item in chunk["resources"]:
            if len(resources) >= 400:
                break
            resources.append(
                {
                    "id": item.get("id"),
                    "name": item.get("name"),
                    "type": item.get("type"),
                    "kind": resource_kind(item),
                    "group": item.get("resourceGroup"),
                    "location": item.get("location"),
                }
            )
    vms = [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "group": item.get("resourceGroup"),
            "location": item.get("location"),
            "size": (item.get("hardwareProfile") or {}).get("vmSize") or "",
            "state": _power_label(item.get("powerState")),
        }
        for chunk in chunks
        for item in chunk["vms"]
    ]
    hosting = [
        *[{"id": item.get("id"), "name": item.get("name"), "kind": "Container App", "group": item.get("resourceGroup"), "location": item.get("location")} for chunk in chunks for item in chunk["apps"]],
        *[{"id": item.get("id"), "name": item.get("name"), "kind": "AKS", "group": item.get("resourceGroup"), "location": item.get("location")} for chunk in chunks for item in chunk["clusters"]],
        *[{"id": item.get("id"), "name": item.get("name"), "kind": "App Service", "group": item.get("resourceGroup"), "location": item.get("location")} for chunk in chunks for item in chunk["sites"]],
    ]
    trend_title = {
        "7d": "Spend · last 7 days",
        "30d": "Spend · last 30 days",
        "qtr": "Spend · this quarter",
    }.get(range_info["id"], "Spend · this month")
    activity = []
    for chunk in chunks:
        for item in chunk["activity"]:
            operation = item.get("operationName")
            if isinstance(operation, dict):
                text = operation.get("localizedValue") or operation.get("value") or "Activity"
                op_value = operation.get("value") or ""
            else:
                text = operation or "Activity"
                op_value = operation or ""
            status = item.get("status")
            status_text = status.get("value") if isinstance(status, dict) else (status or "")
            activity.append(
                {
                    "id": f"{item.get('eventTimestamp') or ''}-{op_value or item.get('id') or len(activity)}",
                    "time": item.get("eventTimestamp") or item.get("submissionTimestamp") or "",
                    "status": status_text,
                    "caller": item.get("caller") or "",
                    "text": text,
                    "resource": str(item.get("resourceId") or "").rsplit("/", maxsplit=1)[-1],
                }
            )
    activity.sort(key=lambda item: item["time"] or "", reverse=True)
    model = {
        **base,
        "status": "ready",
        "message": warnings[0] if warnings else "",
        "warnings": warnings[:8],
        "kpis": {
            "spend": costs["total"] if can_see_cost else None,
            "currency": costs.get("currency") or "USD",
            "forecast": forecast_month(costs["total"], len(days), now) if can_see_cost and range_info["id"] == "mtd" else None,
            "resourceCount": sum(len(chunk["resources"]) for chunk in chunks),
            "vmCount": len(vms),
            "vmRunning": sum(1 for item in vms if item["state"] == "Running"),
            "groupCount": sum(len(chunk["groups"]) for chunk in chunks),
        },
        "trend": {"title": trend_title, "points": costs["points"] if can_see_cost else []},
        "services": costs["services"],
        "groups": groups,
        "databricks": databricks,
        "vms": vms,
        "hosting": hosting,
        "workspaces": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "group": item.get("resourceGroup"),
                "location": item.get("location"),
                "sku": (item.get("sku") or {}).get("name") or "",
            }
            for chunk in chunks
            for item in chunk["workspaces"]
        ],
        "storage": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "group": item.get("resourceGroup"),
                "location": item.get("location"),
                "kind": item.get("kind") or "Storage",
                "hierarchical": bool(item.get("isHnsEnabled")),
            }
            for chunk in chunks
            for item in chunk["storage"]
        ],
        "pipelines": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "group": item.get("resourceGroup"),
                "location": item.get("location"),
            }
            for chunk in chunks
            for item in chunk["factories"]
        ],
        "resources": resources,
        "activity": activity[:12],
        "alerts": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "state": "Disabled" if item.get("enabled") is False else "Enabled",
                "severity": item.get("severity") if item.get("severity") is not None else "",
                "group": item.get("resourceGroup") or "",
            }
            for chunk in chunks
            for item in chunk["alerts"]
        ],
        "advisor": [
            {
                "id": item.get("id") or item.get("name"),
                "impact": item.get("impact") or "",
                "category": item.get("category") or "Advisor",
                "problem": (item.get("shortDescription") or {}).get("problem") or "Recommendation",
                "solution": (item.get("shortDescription") or {}).get("solution") or "",
            }
            for chunk in chunks
            for item in chunk["advisor"]
        ][:30],
        "syncedAt": int(time.time() * 1000),
    }
    if not chunks and warnings:
        model["status"] = "error"
        model["message"] = warnings[0]
    if model["status"] == "ready":
        _CACHE[key] = (time.monotonic(), model)
    return model
