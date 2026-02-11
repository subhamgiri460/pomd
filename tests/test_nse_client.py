"""
Tests for src.nse_client — curl-based NSE data fetcher.

Mocks subprocess.run to simulate curl behavior without actual HTTP calls.
"""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch, MagicMock

import pytest

from src.config import AppConfig, MIN_RESPONSE_BYTES
from src.nse_client import NSEClient, NSEFetchError, NSEValidationError


# ── Helpers ──────────────────────────────────────────────────────────────────

SAMPLE_NSE_DATA = json.dumps({
    "data": [
        {"metadata": {"symbol": "RELIANCE", "purpose": "-", "yearHigh": 3217.60, "yearLow": 1119.50}},
        {"metadata": {"symbol": "TCS", "purpose": "-", "yearHigh": 4592.25, "yearLow": 3056.05}},
        {"metadata": {"symbol": "INFY", "purpose": "-", "yearHigh": 2100.00, "yearLow": 1200.00}},
    ]
}).encode()


def _make_curl_result(
    *,
    returncode: int = 0,
    stdout: str = "200",
    stderr: str = "",
) -> subprocess.CompletedProcess:
    """Create a mock subprocess.CompletedProcess for curl."""
    return subprocess.CompletedProcess(
        args=["curl"],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


# ── Test fetch flow ──────────────────────────────────────────────────────────

class TestNSEClientFetch:
    """Test the curl-based fetch method."""

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_successful_fetch(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should return raw bytes when curl succeeds with HTTP 200."""
        # Mock curl returning HTTP 200
        mock_run.return_value = _make_curl_result(stdout="200")

        client = NSEClient(app_config)

        # We need to intercept the temp directory and file reading
        # Since curl writes to a file, we patch open() to return our sample data
        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open", new_callable=MagicMock) as mock_open:

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            # Setup mock file handle
            mock_file = MagicMock()
            mock_file.read.return_value = SAMPLE_NSE_DATA
            mock_open.return_value.__enter__.return_value = mock_file

            result = client.fetch()

        assert result == SAMPLE_NSE_DATA
        mock_run.assert_called_once()

        # Verify curl was called with correct flags
        call_args = mock_run.call_args
        cmd = call_args[0][0]  # First positional arg is the command list
        assert "--http1.1" in cmd
        assert "-L" in cmd
        assert "--compressed" in cmd
        assert app_config.nse_url in cmd

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_curl_non_zero_exit_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEFetchError when curl exits with non-zero code."""
        mock_run.return_value = _make_curl_result(
            returncode=7, stdout="000", stderr="Failed to connect"
        )

        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open") as mock_open:  # Not used due to exception

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            with pytest.raises(NSEFetchError, match="curl failed"):
                client.fetch()

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_http_403_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEFetchError on HTTP 403."""
        mock_run.return_value = _make_curl_result(stdout="403")

        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open") as mock_open:  # Not used due to exception

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            with pytest.raises(NSEFetchError, match="HTTP 403"):
                client.fetch()

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_response_too_small_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEValidationError when response is too small."""
        mock_run.return_value = _make_curl_result(stdout="200")

        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open") as mock_open:

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            mock_file = MagicMock()
            mock_file.read.return_value = b'{"error": true}'  # Too small
            mock_open.return_value.__enter__.return_value = mock_file

            with pytest.raises(NSEValidationError, match="too small"):
                client.fetch()

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_invalid_json_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEValidationError when response is not JSON."""
        mock_run.return_value = _make_curl_result(stdout="200")

        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open") as mock_open:

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            mock_file = MagicMock()
            mock_file.read.return_value = b"<html>Not JSON</html>" + b"x" * 200
            mock_open.return_value.__enter__.return_value = mock_file

            with pytest.raises(NSEValidationError, match="not valid JSON"):
                client.fetch()

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_non_dict_json_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEValidationError when JSON is a list, not dict."""
        mock_run.return_value = _make_curl_result(stdout="200")

        body = json.dumps([1, 2, 3] * 50).encode()  # list, not dict, big enough

        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open") as mock_open:

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            mock_file = MagicMock()
            mock_file.read.return_value = body
            mock_open.return_value.__enter__.return_value = mock_file

            with pytest.raises(NSEValidationError, match="Expected JSON object"):
                client.fetch()

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("curl", 40))
    def test_timeout_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEFetchError when curl times out."""
        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open"):  # Not used

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            with pytest.raises(NSEFetchError, match="timed out"):
                client.fetch()

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    def test_empty_body_raises(
        self, mock_run: MagicMock, mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEFetchError when response body is empty."""
        mock_run.return_value = _make_curl_result(stdout="200")

        client = NSEClient(app_config)

        with patch("tempfile.TemporaryDirectory") as mock_tmp_dir, \
             patch("builtins.open") as mock_open:

            mock_dir = MagicMock()
            mock_dir.__enter__.return_value = "/tmp/mock_dir"
            mock_dir.__exit__.return_value = None
            mock_tmp_dir.return_value = mock_dir

            mock_file = MagicMock()
            mock_file.read.return_value = b""
            mock_open.return_value.__enter__.return_value = mock_file

            with pytest.raises(NSEFetchError, match="Empty response"):
                client.fetch()


class TestNSEClientInit:
    """Test client initialization."""

    @patch("shutil.which", return_value=None)
    def test_missing_curl_raises(
        self, mock_which: MagicMock, app_config: AppConfig
    ) -> None:
        """Should raise NSEFetchError if curl is not installed."""
        with pytest.raises(NSEFetchError, match="curl is not installed"):
            NSEClient(app_config)


class TestNSEClientContextManager:
    """Test context manager support."""

    @patch("shutil.which", return_value="/usr/bin/curl")
    def test_context_manager(
        self, mock_which: MagicMock, app_config: AppConfig
    ) -> None:
        """Should support with-statement without errors."""
        with NSEClient(app_config) as client:
            assert client is not None
