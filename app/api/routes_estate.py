"""Estate read API. Azure calls use only the selected project's subscriptions."""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.core import auth
from app.core.db import Organization, Project, ProjectConnection, ProjectMembership, SessionLocal, Subscription, User
from app.core.rbac import is_org_manager, live_can
from app.providers.azure_estate import load_estate, range_by_id
from app.tenancy.access import subscriptions_for_project, visible_projects

router = APIRouter()


@router.post("/api/connections/{connection_id}/refresh")
def refresh_connection(
    connection_id: str,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    """Refresh subscriptions for one org connection. Org managers only."""
    from app.providers.azure_cli import AzureCliError, ensure_profile, list_subscriptions, profile_dir
    from app.providers.azure_infra import AzureCredentials
    from app.tenancy.access import AccessError, audit, connection_secrets, replace_subscriptions

    actor = _actor(user)
    org_id = str(actor["org"]["id"])
    if not is_org_manager(actor["membership"]["role"]):
        raise HTTPException(status_code=403, detail="Only an organization admin can refresh Azure subscriptions.")
    if not org_id or auth.other_org_request(user, org_id):
        return {"ok": True, "subscriptions": []}
    try:
        secrets = connection_secrets(connection_id, org_id)
        creds = AzureCredentials(secrets["tenant_id"], secrets["client_id"], secrets["client_secret"])
        ensure_profile(profile_dir(connection_id), creds)
        creds.client_secret = ""
        rows = list_subscriptions(profile_dir(connection_id))
        replace_subscriptions(org_id, connection_id, rows)
    except AccessError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    except AzureCliError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    audit(org_id=org_id, user_id=str(user.get("id") or ""), action="azure.refresh", detail=connection_id)
    return {"ok": True, "subscriptions": rows}


def _org_role(user: dict[str, Any], org_id: str) -> str:
    role = str(user.get("org_role") or "")
    if role:
        return role
    from app.tenancy import memberships

    row = memberships.org_membership(str(user.get("id") or ""), org_id)
    return row.org_role if row is not None else "member"


def _actor(user: dict[str, Any]) -> dict[str, Any]:
    org_id = str(user.get("org_id") or user.get("primary_org_id") or "")
    return {
        "org": {"id": org_id},
        "user": {"id": str(user.get("id") or ""), "name": user.get("name") or user.get("username") or ""},
        "membership": {"role": _org_role(user, org_id) if org_id else "member"},
    }


def _project_role(user_id: str, project_id: str) -> Optional[str]:
    with SessionLocal() as session:
        return session.scalar(
            select(ProjectMembership.project_role).where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.project_id == project_id,
            )
        )


def _workspace(actor: dict[str, Any]) -> dict[str, Any]:
    org_id = str(actor["org"]["id"])
    role = actor["membership"]["role"]
    projects = []
    if org_id:
        for project in visible_projects(actor):
            projects.append(
                {
                    "id": project["id"],
                    "name": project["name"],
                    "budget": project.get("budget_usd"),
                    "role": project.get("role"),
                    "connectionIds": _connection_ids(project["id"], org_id),
                    "subscriptionIds": [item["id"] for item in subscriptions_for_project(project["id"], org_id)],
                }
            )
    payload: dict[str, Any] = {
        "user": actor["user"],
        "org": _org_public(org_id),
        "orgs": _user_orgs(str(actor["user"]["id"])),
        "orgRole": role,
        "canManage": is_org_manager(role),
        "projects": projects,
    }
    if payload["canManage"] and org_id:
        payload["members"] = _members(org_id)
        payload["connections"] = _connections(org_id)
        payload["subscriptions"] = _subscriptions(org_id)
    return payload


def _org_public(org_id: str) -> dict[str, Any]:
    if not org_id:
        return {"id": "", "name": ""}
    with SessionLocal() as session:
        org = session.get(Organization, org_id)
    if org is None:
        return {"id": org_id, "name": ""}
    return {"id": org.id, "name": org.name}


def _user_orgs(user_id: str) -> list[dict[str, Any]]:
    from app.core.db import OrgMembership

    with SessionLocal() as session:
        rows = session.execute(
            select(Organization.id, Organization.name, OrgMembership.org_role)
            .join(OrgMembership, OrgMembership.org_id == Organization.id)
            .where(OrgMembership.user_id == user_id)
            .order_by(Organization.name.asc())
        ).all()
    return [{"id": row.id, "name": row.name, "role": row.org_role} for row in rows]


def _connection_ids(project_id: str, org_id: str) -> list[str]:
    with SessionLocal() as session:
        rows = session.execute(
            select(ProjectConnection.connection_id)
            .join(Project, Project.id == ProjectConnection.project_id)
            .where(ProjectConnection.project_id == project_id, Project.org_id == org_id)
        ).all()
    return [row.connection_id for row in rows]


def _members(org_id: str) -> list[dict[str, Any]]:
    from app.core.db import OrgMembership

    with SessionLocal() as session:
        rows = session.execute(
            select(User.id, User.display_name, User.email, OrgMembership.org_role)
            .join(OrgMembership, OrgMembership.user_id == User.id)
            .where(OrgMembership.org_id == org_id)
            .order_by(User.display_name.asc())
        ).all()
        members = []
        for row in rows:
            projects = session.execute(
                select(Project.id, Project.name, ProjectMembership.project_role)
                .join(ProjectMembership, ProjectMembership.project_id == Project.id)
                .where(ProjectMembership.user_id == row.id, Project.org_id == org_id)
            ).all()
            members.append(
                {
                    "id": row.id,
                    "name": row.display_name,
                    "email": row.email,
                    "role": row.org_role,
                    "projects": [{"id": item.id, "name": item.name, "role": item.project_role} for item in projects],
                }
            )
    return members


def _connections(org_id: str) -> list[dict[str, Any]]:
    from app.core.db import AzureConnection

    with SessionLocal() as session:
        rows = session.scalars(
            select(AzureConnection).where(AzureConnection.org_id == org_id).order_by(AzureConnection.name.asc())
        ).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "status": row.status,
            "statusDetail": row.status_detail or "",
            "lastCheckedAt": row.last_checked_at.isoformat() if row.last_checked_at else None,
            "clientHint": (row.client_id or "")[-4:],
            "secretStored": True,
        }
        for row in rows
    ]


def _subscriptions(org_id: str) -> list[dict[str, Any]]:
    from app.core.db import ProjectSubscription

    with SessionLocal() as session:
        rows = session.execute(
            select(Subscription, ProjectSubscription.project_id)
            .outerjoin(ProjectSubscription, ProjectSubscription.subscription_id == Subscription.id)
            .where(Subscription.org_id == org_id)
            .order_by(Subscription.name.asc())
        ).all()
    return [
        {
            "id": sub.id,
            "name": sub.name,
            "state": sub.state,
            "connectionId": sub.connection_id,
            "projectId": project_id,
        }
        for sub, project_id in rows
    ]


class OrgSwitchBody(BaseModel):
    orgId: str = ""
    org_id: str = ""


@router.post("/api/session/org")
def switch_session_org(
    body: OrgSwitchBody,
    request: Request,
    user: dict[str, Any] = Depends(auth.require_user),
) -> dict[str, Any]:
    from app.tenancy import memberships

    org_id = (body.orgId or body.org_id).strip()
    if memberships.org_membership(str(user.get("id") or ""), org_id) is None and not memberships.is_super_admin(user):
        raise HTTPException(status_code=404, detail="Organization not found.")
    token = request.cookies.get(auth.SESSION_COOKIE)
    if not token or not auth.set_browser_session_org(token, org_id):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"ok": True, "org_id": org_id}


@router.get("/api/workspace")
def workspace(user: dict[str, Any] = Depends(auth.require_user)) -> dict[str, Any]:
    return _workspace(_actor(user))


@router.get("/api/estate")
def get_estate(
    user: dict[str, Any] = Depends(auth.require_user),
    project_id: str = Query(default="", alias="projectId"),
    project_id_snake: str = Query(default="", alias="project_id"),
    range_id: str = Query(default="", alias="range"),
    fresh: str = "0",
) -> dict[str, Any]:
    actor = _actor(user)
    org_id = str(actor["org"]["id"])
    if auth.other_org_request(user, org_id) if org_id else False:
        return {"status": "setup", "subscriptions": [], "warnings": [], "canSeeCost": False}
    chosen_range = range_by_id(range_id)
    projects = visible_projects(actor) if org_id else []
    if not projects:
        message = (
            "An organization admin has not added you to a project yet."
            if actor["membership"]["role"] == "member"
            else "Connect Azure, create a project, and attach the subscriptions that belong to it."
        )
        return {
            "status": "setup",
            "message": message,
            "project": None,
            "range": chosen_range,
            "canSeeCost": False,
            "warnings": [],
            "subscriptions": [],
            "workspace": _workspace(actor),
        }
    requested = project_id or project_id_snake
    project = next((item for item in projects if item["id"] == requested), projects[0])
    if str(project.get("org_id") or "") != org_id:
        raise HTTPException(status_code=404, detail="Project not found.")
    project_role = _project_role(str(user.get("id") or ""), project["id"])
    org_role = actor["membership"]["role"]
    if not live_can(org_role, project_role, "resources.read") and not live_can(org_role, project_role, "billing.read"):
        raise HTTPException(status_code=403, detail="Your role does not allow this project.")
    can_see_cost = live_can(org_role, project_role, "billing.read")
    estate = load_estate(
        org_id=org_id,
        project=project,
        range_id=chosen_range["id"],
        can_see_cost=can_see_cost,
        fresh=fresh == "1",
    )
    estate["workspace"] = _workspace(actor)
    return estate
