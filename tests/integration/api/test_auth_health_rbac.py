"""API health, login, JWT middleware, and viewer write-block."""
from __future__ import annotations

import pytest


pytestmark = pytest.mark.integration


def test_health_is_public(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "skill_count" in body


def test_protected_route_requires_authentication(client):
    response = client.get("/api/auth/me")
    assert response.status_code == 401
    assert "authenticated" in response.json()["detail"].lower()


def test_invalid_and_malformed_tokens_are_rejected(client):
    assert client.get("/api/skills", headers={"Authorization": "Bearer not-a-jwt"}).status_code == 401
    assert client.get("/api/skills", headers={"Authorization": "Token abc"}).status_code == 401
    assert client.get("/api/skills", headers={"Authorization": "Bearer"}).status_code == 401


def test_login_success_and_me(client, make_user):
    user = make_user(role="developer", password="secret12")
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "secret12"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["token"]
    assert "password" not in str(payload).lower() or "password_hash" not in str(payload)
    me = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {payload['token']}"},
    )
    assert me.status_code == 200
    assert me.json()["user"]["username"] == user["username"]
    assert "password_hash" not in me.json()["user"]


def test_login_rejects_invalid_and_missing_credentials(client, make_user):
    user = make_user(password="secret12")
    bad = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "wrong-password"},
    )
    assert bad.status_code == 401
    missing = client.post("/api/auth/login", json={"username": user["username"]})
    assert missing.status_code == 422


def test_inactive_user_cannot_login(client, make_user):
    user = make_user(password="secret12", is_active=False)
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "secret12"},
    )
    assert response.status_code == 401


def test_viewer_can_read_but_cannot_write(client, viewer):
    headers = {"Authorization": f"Bearer {viewer['token']}"}
    skills = client.get("/api/skills", headers=headers)
    assert skills.status_code == 200
    create = client.post("/api/projects", json={"name": "blocked"}, headers=headers)
    assert create.status_code == 403
    assert "read-only" in create.json()["detail"].lower() or "viewer" in create.json()["detail"].lower()


def test_unknown_skill_returns_404(client, developer):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.get("/api/skills/not-a-skill", headers=headers)
    assert response.status_code == 404


def test_roles_endpoint(client, developer):
    headers = {"Authorization": f"Bearer {developer['token']}"}
    response = client.get("/api/roles", headers=headers)
    assert response.status_code == 200
    ids = {row["id"] for row in response.json()}
    assert "super_admin" in ids
    assert "viewer" in ids


def test_logout_deletes_the_session_row(client, make_user):
    from app.core import auth
    from app.core.db import LoginSession, SessionLocal

    user = make_user(role="developer", password="secret12")
    response = client.post(
        "/api/auth/login",
        json={"username": user["username"], "password": "secret12"},
    )
    assert response.status_code == 200
    cookie = response.cookies.get("il_session")
    assert cookie
    digest = auth.session_token_hash(cookie)
    with SessionLocal() as session:
        row = session.get(LoginSession, digest)
        assert row is not None
        assert row.user_id == user["id"]
    client.cookies.clear()
    client.cookies.set("il_session", cookie)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["id"] == user["id"]
    gone = client.post("/api/auth/logout")
    assert gone.status_code == 200
    with SessionLocal() as session:
        assert session.get(LoginSession, digest) is None
    assert client.get("/api/auth/me").status_code == 401


def test_expired_session_is_rejected(client, make_user):
    from datetime import datetime, timedelta, timezone

    from app.core import auth
    from app.core.db import LoginSession, SessionLocal

    user = make_user(role="developer")
    cookie = auth.create_browser_session(user["id"], None)
    with SessionLocal() as session:
        row = session.get(LoginSession, auth.session_token_hash(cookie))
        assert row is not None
        row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=30)
        session.commit()
    client.cookies.set("il_session", cookie)
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_session_hides_another_org(client, make_user):
    from app.core import auth
    from app.tenancy import memberships, orgs, projects

    user = make_user(role="viewer")
    org_a = orgs.create_org(name=f"OrgA-{user['id'][:8]}", created_by=user["id"])
    org_b = orgs.create_org(name=f"OrgB-{user['id'][:8]}", created_by=user["id"])
    projects.create_project("Visible", org_id=org_a["id"], owner_user_id=user["id"])
    projects.create_project("Hidden", org_id=org_b["id"], owner_user_id=user["id"])
    memberships.ensure_org_membership(
        org_id=org_a["id"], user_id=user["id"], org_role="org_owner"
    )
    memberships.ensure_org_membership(
        org_id=org_b["id"], user_id=user["id"], org_role="org_admin"
    )
    cookie = auth.create_browser_session(user["id"], org_a["id"])
    client.cookies.set("il_session", cookie)
    foreign = client.get(f"/api/orgs/{org_b['id']}/projects")
    assert foreign.status_code == 200
    assert foreign.json() == []
    own = client.get(f"/api/orgs/{org_a['id']}/projects")
    assert own.status_code == 200
    assert any(row["name"] == "Visible" for row in own.json())
    listed = client.get("/api/orgs")
    assert [row["id"] for row in listed.json()] == [org_a["id"]]


def test_signup_creates_owner_and_cannot_see_or_create_another_org(client, make_user):
    from app.tenancy import orgs

    admin = make_user(role="super_admin")
    other = orgs.create_org(name=f"Existing-{admin['id'][:8]}", created_by=admin["id"])
    email = f"ada-{admin['id'][:8]}@example.com"
    response = client.post(
        "/api/signup",
        json={
            "name": "Ada Lovelace",
            "orgName": "Ada Org",
            "email": email,
            "password": "password1",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.cookies.get("il_session")
    assert "password" not in response.text
    listed = client.get("/api/orgs")
    assert listed.status_code == 200
    ids = [row["id"] for row in listed.json()]
    assert other["id"] not in ids
    assert len(ids) == 1
    denied = client.post("/api/orgs", json={"name": "Sibling"})
    assert denied.status_code == 403


def test_operator_bearer_cannot_write(client, make_user):
    user = make_user(role="operator", password="secret12")
    response = client.post(
        "/api/projects",
        json={"name": "blocked-operator"},
        headers={"Authorization": f"Bearer {user['token']}"},
    )
    assert response.status_code == 403
