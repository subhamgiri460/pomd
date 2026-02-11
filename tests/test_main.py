"""
Integration tests for src.main — full pipeline orchestration.

Tests the run_pipeline function with mocked external dependencies
(NSE via subprocess mock, GitHub via HTTP mock) to verify the complete flow.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

import pytest
import responses

from src.config import AppConfig
from src.main import run_pipeline, PipelineResult, update_log
from src.log_manager import RunStatus
from tests.conftest import (
    sample_nse_bytes,
    sample_index_bytes,
    SAMPLE_INDEX,
    FIXED_TIMESTAMP,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _setup_github_get(
    config: AppConfig,
    path: str,
    content: bytes | None,
    sha: str = "existing_sha",
) -> None:
    """Register a GitHub GET mock for a file."""
    url = f"{config.github_api_url}/{path}"
    if content is None:
        responses.add(responses.GET, url, json={"message": "Not Found"}, status=404)
    else:
        responses.add(
            responses.GET,
            url,
            json={
                "content": base64.b64encode(content).decode(),
                "sha": sha,
            },
            status=200,
        )


def _setup_github_put(config: AppConfig) -> None:
    """Register a GitHub PUT mock matching any path under the API URL."""
    api_pattern = re.compile(re.escape(config.github_api_url) + r"/.*")
    responses.add(
        responses.PUT,
        api_pattern,
        json={"commit": {"sha": "commit1"}},
        status=201,
    )


# ── Test Pipeline Success ────────────────────────────────────────────────────

class TestRunPipelineSuccess:
    """Test the happy path — new data gets archived."""

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    @patch("tempfile.TemporaryDirectory")
    @patch("builtins.open")
    def test_new_data_archived(
        self,
        mock_open: MagicMock,
        mock_tmp_dir: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_time: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should upload .gz and update index when data is new."""
        body = sample_nse_bytes()

        # Mock directory
        mock_dir = MagicMock()
        mock_dir.__enter__.return_value = "/tmp/mock_dir"
        mock_dir.__exit__.return_value = None
        mock_tmp_dir.return_value = mock_dir

        # Mock open to return body
        mock_file = MagicMock()
        mock_file.read.return_value = body
        mock_open.return_value.__enter__.return_value = mock_file

        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"], returncode=0, stdout="200", stderr=""
        )

        # GitHub mocks
        _setup_github_get(app_config, "index.json", sample_index_bytes())
        _setup_github_put(app_config)

        result = run_pipeline(app_config)

        assert result.status == RunStatus.SUCCESS
        assert result.filename is not None
        assert result.filename.endswith(".json.gz")
        assert "Archived" in result.message

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    @patch("tempfile.TemporaryDirectory")
    @patch("builtins.open")
    def test_creates_index_when_missing(
        self,
        mock_open: MagicMock,
        mock_tmp_dir: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_time: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should create index.json when it doesn't exist yet."""
        body = sample_nse_bytes()

        # Mock directory
        mock_dir = MagicMock()
        mock_dir.__enter__.return_value = "/tmp/mock_dir"
        mock_dir.__exit__.return_value = None
        mock_tmp_dir.return_value = mock_dir

        # Mock open to return body
        mock_file = MagicMock()
        mock_file.read.return_value = body
        mock_open.return_value.__enter__.return_value = mock_file

        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"], returncode=0, stdout="200", stderr=""
        )

        _setup_github_get(app_config, "index.json", None)  # 404
        _setup_github_put(app_config)

        result = run_pipeline(app_config)

        assert result.status == RunStatus.SUCCESS


# ── Test Duplicate Detection ─────────────────────────────────────────────────

class TestRunPipelineDuplicate:
    """Test the duplicate detection path."""

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    @patch("tempfile.TemporaryDirectory")
    @patch("builtins.open")
    def test_duplicate_data_skipped(
        self,
        mock_open: MagicMock,
        mock_tmp_dir: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_time: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should skip upload when hash already exists in index."""
        nse_data = sample_nse_bytes()

        mock_dir = MagicMock()
        mock_dir.__enter__.return_value = "/tmp/mock_dir"
        mock_dir.__exit__.return_value = None
        mock_tmp_dir.return_value = mock_dir

        mock_file = MagicMock()
        mock_file.read.return_value = nse_data
        mock_open.return_value.__enter__.return_value = mock_file

        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"], returncode=0, stdout="200", stderr=""
        )

        # Build index with the exact hash of this data
        from src.compression import gzip_compress, sha256_hex

        compressed = gzip_compress(nse_data)
        data_hash = sha256_hex(compressed)

        index_with_hash = {
            "version": 1,
            "files": [
                {
                    "filename": "existing_file.json.gz",
                    "hash": data_hash,
                    "timestamp": "2026-02-10T03:38:00Z",
                    "size_bytes": len(compressed),
                    "raw_size_bytes": len(nse_data),
                    "records_count": 2,
                }
            ],
            "total_count": 1,
            "last_updated": "2026-02-10T03:38:05Z",
        }
        index_bytes = json.dumps(index_with_hash).encode()

        _setup_github_get(app_config, "index.json", index_bytes)

        result = run_pipeline(app_config)

        assert result.status == RunStatus.DUPLICATE
        assert "Duplicate" in result.message
        assert result.filename is None
        # Should NOT have made any PUT calls
        put_calls = [c for c in responses.calls if c.request.method == "PUT"]
        assert len(put_calls) == 0


# ── Test Error Handling ──────────────────────────────────────────────────────

class TestRunPipelineErrors:
    """Test error handling paths."""

    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    @patch("tempfile.TemporaryDirectory")
    @patch("builtins.open")
    def test_nse_fetch_failure(
        self,
        mock_open: MagicMock,
        mock_tmp_dir: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise NSEFetchError when curl returns non-zero."""
        mock_dir = MagicMock()
        mock_dir.__enter__.return_value = "/tmp/mock_dir"
        mock_dir.__exit__.return_value = None
        mock_tmp_dir.return_value = mock_dir

        # open() won't be called because subprocess returns non-zero

        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"], returncode=7, stdout="000",
            stderr="Failed to connect"
        )

        from src.nse_client import NSEFetchError

        with pytest.raises(NSEFetchError):
            run_pipeline(app_config)

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    @patch("shutil.which", return_value="/usr/bin/curl")
    @patch("subprocess.run")
    @patch("tempfile.TemporaryDirectory")
    @patch("builtins.open")
    def test_github_upload_failure(
        self,
        mock_open: MagicMock,
        mock_tmp_dir: MagicMock,
        mock_run: MagicMock,
        mock_which: MagicMock,
        mock_time: MagicMock,
        app_config: AppConfig,
    ) -> None:
        """Should raise GitHubAPIError when upload fails."""
        body = sample_nse_bytes()

        mock_dir = MagicMock()
        mock_dir.__enter__.return_value = "/tmp/mock_dir"
        mock_dir.__exit__.return_value = None
        mock_tmp_dir.return_value = mock_dir

        mock_file = MagicMock()
        mock_file.read.return_value = body
        mock_open.return_value.__enter__.return_value = mock_file

        mock_run.return_value = subprocess.CompletedProcess(
            args=["curl"], returncode=0, stdout="200", stderr=""
        )

        _setup_github_get(app_config, "index.json", None)  # New index

        # Data upload fails
        api_pattern = re.compile(re.escape(app_config.github_api_url) + r"/.*")
        responses.add(
            responses.PUT,
            api_pattern,
            json={"message": "Conflict"},
            status=409,
        )

        from src.github_repo import GitHubAPIError

        with pytest.raises(GitHubAPIError):
            run_pipeline(app_config)


# ── Test PipelineResult ──────────────────────────────────────────────────────

class TestPipelineResult:
    """Test PipelineResult helper methods."""

    def test_success_is_not_error(self) -> None:
        result = PipelineResult(RunStatus.SUCCESS, "ok", filename="test.gz")
        assert result.is_error is False

    def test_duplicate_is_not_error(self) -> None:
        result = PipelineResult(RunStatus.DUPLICATE, "skip")
        assert result.is_error is False

    def test_error_is_error(self) -> None:
        result = PipelineResult(RunStatus.ERROR, "failed")
        assert result.is_error is True


# ── Test Log Update ──────────────────────────────────────────────────────────

class TestUpdateLog:
    """Test the log update step."""

    @responses.activate
    def test_update_log_success(self, app_config: AppConfig) -> None:
        """Should fetch, update, and push log.json."""
        _setup_github_get(app_config, "log.json", None)  # New log
        api_pattern = re.compile(re.escape(app_config.github_api_url) + r"/.*")
        responses.add(
            responses.PUT,
            api_pattern,
            json={"commit": {"sha": "commit1"}},
            status=201,
        )

        result = PipelineResult(
            RunStatus.SUCCESS, "test run", filename="test.gz"
        )
        # Should not raise
        update_log(app_config, result, duration_ms=5000)

    @responses.activate
    def test_update_log_failure_does_not_raise(
        self, app_config: AppConfig
    ) -> None:
        """Log update failure should be swallowed (best-effort)."""
        responses.add(
            responses.GET,
            f"{app_config.github_api_url}/log.json",
            json={"message": "Server Error"},
            status=500,
        )

        result = PipelineResult(RunStatus.ERROR, "test")
        # Should NOT raise even though GitHub API fails
        update_log(app_config, result, duration_ms=1000)
