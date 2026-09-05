"""Tests for Oura API client OAuth token refresh."""

from unittest.mock import MagicMock, patch
import requests

from src.oura.api_client import OuraAPIClient


def test_oura_client_ensure_auth_refreshes_proactively():
    client = OuraAPIClient(
        client_id="cid",
        client_secret="csecret",
        access_token="old_access",
        refresh_token="old_refresh",
    )

    with patch.object(client, "refresh_access_token", return_value=True) as mock_refresh:
        assert client.ensure_auth() is True
        mock_refresh.assert_called_once()


def test_oura_client_ensure_auth_falls_back_when_no_refresh_token():
    client = OuraAPIClient(
        client_id="cid",
        client_secret="csecret",
        access_token="valid_access",
        refresh_token="",
    )

    assert client.ensure_auth() is True


def test_oura_client_refresh_access_token_success(tmp_path):
    env_file = tmp_path / ".env"
    client = OuraAPIClient(
        client_id="cid",
        client_secret="csecret",
        access_token="old_acc",
        refresh_token="old_ref",
    )

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {
        "access_token": "new_acc",
        "refresh_token": "new_ref",
    }

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post, \
         patch("src.oura.api_client.save_tokens_to_env") as mock_save:
        success = client.refresh_access_token()
        assert success is True
        assert client.access_token == "new_acc"
        assert client.refresh_token == "new_ref"
        assert client._refresh_failed is False
        mock_save.assert_called_once_with("OURA", "new_acc", "new_ref")


def test_oura_client_refresh_access_token_failure_handles_error_response():
    client = OuraAPIClient(
        client_id="cid",
        client_secret="csecret",
        access_token="old_acc",
        refresh_token="invalid_ref",
    )

    mock_resp = MagicMock()
    mock_resp.ok = False
    mock_resp.status_code = 400
    mock_resp.json.return_value = {
        "error": "invalid_grant",
        "error_description": "Refresh token is invalid or expired",
    }

    with patch.object(client.session, "post", return_value=mock_resp):
        success = client.refresh_access_token()
        assert success is False
        assert client._refresh_failed is True


def test_oura_client_make_request_does_not_repeat_refresh_if_already_failed():
    client = OuraAPIClient(
        client_id="cid",
        client_secret="csecret",
        access_token="old_acc",
        refresh_token="invalid_ref",
    )
    client._refresh_failed = True

    mock_resp = MagicMock()
    mock_resp.status_code = 401

    with patch.object(client.session, "get", return_value=mock_resp), \
         patch.object(client, "refresh_access_token") as mock_refresh:
        res = client._make_request("https://api.ouraring.com/v2/usercollection/daily_activity")
        assert res is None
        mock_refresh.assert_not_called()
