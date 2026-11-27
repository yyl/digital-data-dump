from unittest.mock import MagicMock

import pytest
import requests

from src.letterboxd.tmdb_client import TMDBAPIError, TMDBClient


def test_tmdb_client_prefers_exact_title_and_year_match():
    client = TMDBClient(access_token="token")
    client._make_request = lambda path, params=None: {  # type: ignore[method-assign]
        "results": [
            {"id": 1, "title": "The Substance", "original_title": "The Substance", "release_date": "2024-09-07"},
            {"id": 2, "title": "The Substance", "original_title": "The Substance", "release_date": "2025-01-01"},
        ]
    } if path == "/search/movie" else {"runtime": 141}

    match = client.get_runtime(title="The Substance", year=2024)

    assert match == (1, 141)


def test_tmdb_client_rejects_fuzzy_title_matches():
    client = TMDBClient(access_token="token")
    client._make_request = lambda path, params=None: {  # type: ignore[method-assign]
        "results": [
            {"id": 1, "title": "Substance", "original_title": "Substance", "release_date": "2024-09-07"},
        ]
    } if path == "/search/movie" else {"runtime": 141}

    match = client.get_runtime(title="The Substance", year=2024)

    assert match is None


def test_tmdb_client_allows_one_year_release_fallback_for_exact_title():
    client = TMDBClient(access_token="token")

    def fake_request(path, params=None):  # type: ignore[no-untyped-def]
        if path != "/search/movie":
            return {"runtime": 102}
        if params == {"query": "Synchronic", "year": 2019}:
            return {"results": []}
        if params == {"query": "Synchronic"}:
            return {
                "results": [
                    {"id": 10, "title": "Synchronic", "original_title": "Synchronic", "release_date": "2020-10-23"}
                ]
            }
        return {"results": []}

    client._make_request = fake_request  # type: ignore[method-assign]

    match = client.get_runtime(title="Synchronic", year=2019)

    assert match == (10, 102)


def test_tmdb_client_rejects_large_year_gap_even_on_fallback():
    client = TMDBClient(access_token="token")

    def fake_request(path, params=None):  # type: ignore[no-untyped-def]
        if path != "/search/movie":
            return {"runtime": 90}
        if params == {"query": "The Blackening", "year": 2022}:
            return {"results": []}
        if params == {"query": "The Blackening"}:
            return {
                "results": [
                    {
                        "id": 20,
                        "title": "The Blackening",
                        "original_title": "The Blackening",
                        "release_date": "2024-01-01",
                    }
                ]
            }
        return {"results": []}

    client._make_request = fake_request  # type: ignore[method-assign]

    match = client.get_runtime(title="The Blackening", year=2022)

    assert match is None


def test_tmdb_client_fails_immediately_on_auth_error_without_leaking_credentials(monkeypatch):
    session = MagicMock()
    response = MagicMock(status_code=401)
    session.get.return_value = response
    sleep = MagicMock()
    monkeypatch.setattr("src.letterboxd.tmdb_client.time.sleep", sleep)

    client = TMDBClient(access_token="", api_key="super-secret-api-key", session=session)
    client._rate_limit = lambda: None  # type: ignore[method-assign]

    with pytest.raises(TMDBAPIError, match="HTTP 401") as exc_info:
        client.get_runtime(title="Source Code", year=2011)

    assert "super-secret-api-key" not in str(exc_info.value)
    assert session.get.call_count == 1
    sleep.assert_not_called()


def test_tmdb_client_retries_transient_errors_then_raises(monkeypatch):
    session = MagicMock()
    session.get.side_effect = requests.exceptions.Timeout("timeout?api_key=secret-key")
    sleep = MagicMock()
    monkeypatch.setattr("src.letterboxd.tmdb_client.time.sleep", sleep)

    client = TMDBClient(access_token="", api_key="secret-key", session=session)
    client._rate_limit = lambda: None  # type: ignore[method-assign]

    with pytest.raises(TMDBAPIError, match="timed out") as exc_info:
        client.get_runtime(title="Source Code", year=2011)

    assert "secret-key" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None
    assert session.get.call_count == client.MAX_RETRIES
    assert sleep.call_count == client.MAX_RETRIES - 1


def test_tmdb_client_retries_server_and_rate_limit_errors_then_raises(monkeypatch):
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=429)
    sleep = MagicMock()
    monkeypatch.setattr("src.letterboxd.tmdb_client.time.sleep", sleep)

    client = TMDBClient(access_token="secret-token", api_key="", session=session)
    client._rate_limit = lambda: None  # type: ignore[method-assign]

    with pytest.raises(TMDBAPIError, match="HTTP 429") as exc_info:
        client.get_runtime(title="Source Code", year=2011)

    assert "secret-token" not in str(exc_info.value)
    assert session.get.call_count == client.MAX_RETRIES


def test_tmdb_client_treats_404_on_movie_details_as_miss_but_fails_on_search_404():
    session = MagicMock()
    session.get.return_value = MagicMock(status_code=404)
    client = TMDBClient(access_token="token", api_key="", session=session)
    client._rate_limit = lambda: None  # type: ignore[method-assign]

    assert client.get_runtime(title="Missing Film", year=2020, tmdb_id=999999) is None

    with pytest.raises(TMDBAPIError, match="HTTP 404"):
        client.get_runtime(title="Missing Film", year=2020)


def test_tmdb_client_raises_on_invalid_json():
    session = MagicMock()
    response = MagicMock(status_code=200)
    response.json.side_effect = ValueError("bad json")
    session.get.return_value = response
    client = TMDBClient(access_token="token", api_key="", session=session)
    client._rate_limit = lambda: None  # type: ignore[method-assign]

    with pytest.raises(TMDBAPIError, match="invalid JSON"):
        client.get_runtime(title="Source Code", year=2011)


def test_tmdb_client_unconfigured_request_raises():
    client = TMDBClient(access_token="", api_key="")

    with pytest.raises(TMDBAPIError, match="not configured"):
        client.get_runtime(title="Source Code", year=2011)
