"""RBAC hierarchy, aliases, capabilities, and FastAPI guards."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core import rbac


@pytest.mark.unit
def test_normalize_role_aliases_and_unknown():
    assert rbac.normalize_role("admin") == "super_admin"
    assert rbac.normalize_role("superadmin") == "super_admin"
    assert rbac.normalize_role("Org Admin") == "org_admin"
    assert rbac.normalize_role("lead") == "devops_lead"
    assert rbac.normalize_role("engineer") == "devops_engineer"
    assert rbac.normalize_role("dev") == "developer"
    assert rbac.normalize_role("readonly") == "viewer"
    assert rbac.normalize_role("read-only") == "viewer"
    assert rbac.normalize_role(None) == "developer"
    assert rbac.normalize_role("") == "developer"
    assert rbac.normalize_role("not-a-role") == "developer"


@pytest.mark.unit
def test_role_rank_order():
    ranks = [rbac.role_rank(role) for role in rbac.ROLE_ORDER]
    assert ranks == sorted(ranks)
    assert rbac.role_rank("super_admin") > rbac.role_rank("viewer")
    assert rbac.role_rank("unknown") == rbac.role_rank("developer")


@pytest.mark.unit
@pytest.mark.parametrize(
    "role,minimum,expected",
    [
        ("viewer", "viewer", True),
        ("viewer", "developer", False),
        ("developer", "viewer", True),
        ("devops_lead", "devops_engineer", True),
        ("org_admin", "super_admin", False),
        ("super_admin", "org_admin", True),
    ],
)
def test_has_min_role(role, minimum, expected):
    assert rbac.has_min_role(role, minimum) is expected


@pytest.mark.unit
def test_unknown_capability_requires_super_admin():
    assert not rbac.can({"role": "org_admin"}, "not_a_real_capability")
    assert rbac.can({"role": "super_admin"}, "not_a_real_capability")


@pytest.mark.unit
def test_every_capability_has_a_defined_minimum():
    for capability, minimum in rbac.CAPABILITY_MIN_ROLE.items():
        assert minimum in rbac.ROLE_LABELS
        assert rbac.can({"role": "super_admin"}, capability)


@pytest.mark.unit
def test_assert_capability_raises_http_403():
    with pytest.raises(HTTPException) as exc:
        rbac.assert_capability({"role": "viewer"}, "propose_write")
    assert exc.value.status_code == 403
    assert "role" in exc.value.detail.lower() or "Requires" in exc.value.detail


@pytest.mark.unit
def test_assert_capability_allows_when_permitted():
    rbac.assert_capability({"role": "developer"}, "propose_write")


@pytest.mark.unit
def test_can_approve_gate_unknown_defaults_to_lead():
    assert not rbac.can_approve_gate({"role": "developer"}, "mystery_gate")
    assert rbac.can_approve_gate({"role": "devops_lead"}, "mystery_gate")


@pytest.mark.unit
def test_public_roles_covers_hierarchy():
    ids = {item["id"] for item in rbac.public_roles()}
    assert ids == set(rbac.ROLE_LABELS)
    assert all("label" in item for item in rbac.public_roles())


@pytest.mark.unit
def test_require_capability_dependency_rejects():
    dep = rbac.require_capability("manage_users")
    with pytest.raises(HTTPException) as exc:
        dep(user={"role": "developer", "id": "u1"})
    assert exc.value.status_code == 403


@pytest.mark.unit
def test_require_capability_dependency_allows():
    dep = rbac.require_capability("read")
    user = {"role": "viewer", "id": "u1"}
    assert dep(user=user) is user


@pytest.mark.unit
def test_require_min_role_dependency():
    dep = rbac.require_min_role("org_admin")
    with pytest.raises(HTTPException) as exc:
        dep(user={"role": "developer"})
    assert exc.value.status_code == 403
    assert dep(user={"role": "org_admin"})["role"] == "org_admin"


# B-01 through B-22. Unknown capabilities stay super-admin via the fallthrough.
_CAPABILITIES = {
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


@pytest.mark.unit
def test_capability_minimums_match_the_suite_ladder():
    assert rbac.CAPABILITY_MIN_ROLE == _CAPABILITIES
    assert set(_CAPABILITIES) == set(rbac.CAPABILITY_MIN_ROLE)
    for capability, minimum in _CAPABILITIES.items():
        assert rbac.can({"role": minimum}, capability)
        if minimum != "viewer":
            assert not rbac.can({"role": "viewer"}, capability)


@pytest.mark.unit
def test_live_permissions_and_operator_does_not_inherit_developer():
    # B-26 org-manager only. A project admin cannot manage the connection.
    for permission in ("connection.manage", "members.manage", "project.create"):
        assert rbac.live_can("org_owner", None, permission)
        assert rbac.live_can("org_admin", None, permission)
        assert not rbac.live_can("member", "project_admin", permission)
    # B-27 project admin
    for permission in ("project.read", "billing.read", "resources.read", "project.manage"):
        assert rbac.live_can("member", "project_admin", permission)
    assert not rbac.can({"role": "project_admin"}, "prod_apply")
    assert not rbac.can({"role": "project_admin"}, "chat")
    # B-28 billing reader can see cost and cannot write
    for permission in ("project.read", "billing.read", "resources.read"):
        assert rbac.live_can("member", "billing_reader", permission)
    assert not rbac.live_can("member", "billing_reader", "project.manage")
    assert not rbac.can({"role": "billing_reader"}, "propose_write")
    # B-29 operator has no billing and no suite write
    assert rbac.live_can("member", "operator", "project.read")
    assert rbac.live_can("member", "operator", "resources.read")
    assert not rbac.live_can("member", "operator", "billing.read")
    assert rbac.normalize_role("operator") == "developer"
    assert not rbac.can({"role": "operator"}, "propose_write")
    assert not rbac.can({"role": "operator"}, "chat")
    assert rbac.can({"role": "operator"}, "read")
    # B-30 viewer reads cost and inventory, and the suite viewer cannot write
    for permission in ("project.read", "billing.read", "resources.read"):
        assert rbac.live_can("member", "viewer", permission)
    assert not rbac.can({"role": "viewer"}, "chat")
    assert not rbac.can({"role": "viewer"}, "propose_write")
    assert not rbac.can({"role": "viewer"}, "prod_apply")
    assert not rbac.live_can("member", "viewer", "connection.manage")
    # B-32 a member with no project role fails
    assert not rbac.live_can("member", None, "project.read")
    assert not rbac.live_can("member", "", "billing.read")


@pytest.mark.unit
def test_org_owner_has_org_admin_powers_not_super_admin():
    owner = {"role": "viewer", "org_role": "org_owner"}
    assert rbac.suite_role(owner) == "org_admin"
    assert rbac.can(owner, "manage_users")
    assert rbac.can(owner, "invite_users")
    assert rbac.can(owner, "manage_org")
    assert not rbac.can(owner, "create_org")
    assert not rbac.can(owner, "system_settings")
    assert rbac.can({"role": "org_admin"}, "manage_users")
    assert not rbac.can({"role": "org_admin"}, "create_org")


@pytest.mark.unit
def test_merged_role_labels():
    assert rbac.role_label("org_owner") == "Organization owner"
    assert rbac.role_label("org_admin") == "Organization admin"
    assert rbac.role_label("member") == "Member"
    assert rbac.role_label("project_admin") == "Project admin"
    assert rbac.role_label("billing_reader") == "Billing reader"
    assert rbac.role_label("operator") == "Operator"
    assert rbac.role_label("viewer") == "Viewer"
    assert rbac.role_label("super_admin") == "Super Admin"
    assert rbac.role_label("devops_lead") == "DevOps Lead"
    assert rbac.role_label("devops_engineer") == "DevOps Engineer"
    assert rbac.role_label("developer") == "Developer"
    assert rbac.ROLE_LABELS["org_admin"] == "Org Admin"
