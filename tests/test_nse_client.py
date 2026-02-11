"""Tests for src.nse_client — NSE HTTP client with session and validation."""

from __future__ import annotations

import json

import pytest
import responses

from src.config import NSE_BASE_URL, AppConfig
from src.nse_client import NSEClient, NSEFetchError, NSEValidationError
from tests.conftest import sample_nse_bytes


@pytest.fixture
def nse_client(app_config: AppConfig) -> NSEClient:
    """Create an NSEClient instance for testing."""
    return NSEClient(app_config)


class TestNSEClientFetch:
    """Test the full fetch flow with mocked HTTP."""

    @responses.activate
    def test_successful_fetch(self, nse_client: NSEClient) -> None:
        """Should return raw bytes on successful fetch."""
        # Mock homepage (for cookies)
        responses.add(
            responses.GET,
            NSE_BASE_URL,
            body="<html>NSE Homepage</html>",
            status=200,
        )
        # Mock API endpoint
        body = sample_nse_bytes()
        responses.add(
            responses.GET,
            nse_client._config.nse_url,
            body=body,
            status=200,
            content_type="application/json",
        )

        result = nse_client.fetch()
        assert result == body
        assert len(responses.calls) == 2  # homepage + API

    @responses.activate
    def test_homepage_failure_raises(self, nse_client: NSEClient) -> None:
        """Should raise NSEFetchError if homepage fails."""
        responses.add(
            responses.GET,
            NSE_BASE_URL,
            body="Service Unavailable",
            status=503,
        )

        with pytest.raises(NSEFetchError, match="establish NSE session"):
            nse_client.fetch()

    @responses.activate
    def test_api_non_200_raises(self, nse_client: NSEClient) -> None:
        """Should raise NSEFetchError on non-2xx API response."""
        responses.add(responses.GET, NSE_BASE_URL, status=200)
        responses.add(
            responses.GET,
            nse_client._config.nse_url,
            body="Forbidden",
            status=403,
        )

        with pytest.raises(NSEFetchError, match="HTTP 403"):
            nse_client.fetch()

    @responses.activate
    def test_response_too_small_raises(self, nse_client: NSEClient) -> None:
        """Should raise NSEValidationError for tiny responses."""
        responses.add(responses.GET, NSE_BASE_URL, status=200)
        responses.add(
            responses.GET,
            nse_client._config.nse_url,
            body=b"{}",  # Only 2 bytes, below MIN_RESPONSE_BYTES
            status=200,
            content_type="application/json",
        )

        with pytest.raises(NSEValidationError, match="too small"):
            nse_client.fetch()

    @responses.activate
    def test_invalid_json_raises(self, nse_client: NSEClient) -> None:
        """Should raise NSEValidationError for non-JSON responses."""
        responses.add(responses.GET, NSE_BASE_URL, status=200)
        # Return something big enough but not valid JSON
        garbage = b"<html>Not JSON at all</html>" + b"x" * 200
        responses.add(
            responses.GET,
            nse_client._config.nse_url,
            body=garbage,
            status=200,
            content_type="text/html",
        )

        with pytest.raises(NSEValidationError, match="not valid JSON"):
            nse_client.fetch()

    @responses.activate
    def test_non_dict_json_raises(self, nse_client: NSEClient) -> None:
        """Should raise NSEValidationError if JSON is not an object."""
        responses.add(responses.GET, NSE_BASE_URL, status=200)
        # Return a JSON array instead of object
        body = json.dumps(list(range(200))).encode()
        responses.add(
            responses.GET,
            nse_client._config.nse_url,
            body=body,
            status=200,
            content_type="application/json",
        )

        with pytest.raises(NSEValidationError, match="Expected JSON object"):
            nse_client.fetch()


class TestNSEClientContextManager:
    """Test context manager behavior."""

    def test_context_manager_closes_session(self, app_config: AppConfig) -> None:
        """Should close session on context exit."""
        with NSEClient(app_config) as client:
            assert client._session is not None
        # Session should be closed (no easy way to check, just ensure no error)
