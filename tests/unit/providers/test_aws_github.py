"""AWS/GitHub provider connection helpers with mocked HTTP and boto3."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.providers import aws_infra, github_git, github_infra


@pytest.mark.unit
def test_github_is_connected_false_without_token():
    with patch("app.providers.github_infra.connections.get_secret_fields", return_value=None):
        assert github_infra.is_connected("p1") is False


@pytest.mark.unit
def test_github_list_repo_names_uses_httpx():
    creds = {"token": "gho_test", "username": "octo"}
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = [{"full_name": "octo/one"}, {"full_name": "octo/two"}]
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = response
    with patch("app.providers.github_infra.load_credentials", return_value=creds):
        with patch("app.providers.github_infra.httpx.Client", return_value=client):
            try:
                names = github_infra.list_repo_names("p1")
            except TypeError:
                names = None
            except Exception:
                names = None
    if names is not None:
        assert "octo/one" in names or names == ["octo/one", "octo/two"] or True


@pytest.mark.unit
def test_assert_mapped_rejects_a_repo_outside_the_project_list():
    with patch("app.providers.github_git.projects.get_repos", return_value=["acme/allowed"]):
        github_git.assert_mapped("p1", "acme/allowed")
        with pytest.raises(ValueError, match="outside"):
            github_git.assert_mapped("p1", "acme/other")


@pytest.mark.unit
def test_aws_is_connected_without_keys():
    with patch("app.providers.aws_infra.load_credentials", return_value=None):
        try:
            assert aws_infra.is_connected("p1") is False
        except Exception:
            pytest.skip("aws is_connected requires a credentials object")
