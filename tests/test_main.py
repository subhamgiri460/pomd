"""
Integration tests for src.main — full pipeline orchestration.

Tests the run_pipeline function with mocked external dependencies
(NSE API and GitHub API) to verify the complete flow.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
import responses

from src.config import AppConfig, NSE_BASE_URL
from src.main import run_pipeline, PipelineResult, update_log
from src.log_manager import RunStatus
from tests.conftest import (
    sample_nse_bytes,
    sample_index_bytes,
    SAMPLE_INDEX,
    FIXED_TIMESTAMP,
)


def _setup_nse_mocks(config: AppConfig, body: bytes | None = None) -> None:
    """Register NSE homepage and API mocks."""
    responses.add(responses.GET, NSE_BASE_URL, status=200)
    responses.add(
        responses.GET,
        config.nse_url,
        body=body or sample_nse_bytes(),
        status=200,
        content_type="application/json",
    )


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


def _setup_github_put(config: AppConfig, path: str) -> None:
    """Register a GitHub PUT mock."""
    url = f"{config.github_api_url}/{path}"
    responses.add(
        responses.PUT,
        url,
        json={"commit": {"sha": "new_commit_sha"}},
        status=201,
    )


class TestRunPipelineSuccess:
    """Test the happy path — new data gets archived."""

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    def test_new_data_archived(
        self, mock_time: object, app_config: AppConfig
    ) -> None:
        """Should upload .gz and update index when data is new."""
        # Setup mocks
        _setup_nse_mocks(app_config)
        _setup_github_get(app_config, "index.json", sample_index_bytes())
        # We need to allow two PUT calls — data file and index update
        # Use a regex to match any PUT to the GitHub Contents API
        api_pattern = re.compile(re.escape(app_config.github_api_url) + r"/.*")
        responses.add(
            responses.PUT,
            api_pattern,
            json={"commit": {"sha": "commit1"}},
            status=201,
        )

        result = run_pipeline(app_config)

        assert result.status == RunStatus.SUCCESS
        assert result.filename is not None
        assert result.filename.endswith(".json.gz")
        assert "Archived" in result.message

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    def test_creates_index_when_missing(
        self, mock_time: object, app_config: AppConfig
    ) -> None:
        """Should create index.json when it doesn't exist yet."""
        _setup_nse_mocks(app_config)
        _setup_github_get(app_config, "index.json", None)  # 404
        api_pattern = re.compile(re.escape(app_config.github_api_url) + r"/.*")
        responses.add(
            responses.PUT,
            api_pattern,
            json={"commit": {"sha": "commit1"}},
            status=201,
        )

        result = run_pipeline(app_config)

        assert result.status == RunStatus.SUCCESS


class TestRunPipelineDuplicate:
    """Test the duplicate detection path."""

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    def test_duplicate_data_skipped(
        self, mock_time: object, app_config: AppConfig
    ) -> None:
        """Should skip upload when hash already exists in index."""
        nse_data = sample_nse_bytes()

        # We need to construct an index that contains the hash of the
        # gzipped version of this exact data
        from src.compression import gzip_compress, sha256_hex

        compressed = gzip_compress(nse_data)
        data_hash = sha256_hex(compressed)

        # Build index with this hash already present
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

        _setup_nse_mocks(app_config, body=nse_data)
        _setup_github_get(app_config, "index.json", index_bytes)

        result = run_pipeline(app_config)

        assert result.status == RunStatus.DUPLICATE
        assert "Duplicate" in result.message
        assert result.filename is None
        # Should NOT have made any PUT calls
        put_calls = [c for c in responses.calls if c.request.method == "PUT"]
        assert len(put_calls) == 0


class TestRunPipelineErrors:
    """Test error handling paths."""

    @responses.activate
    def test_nse_fetch_failure(self, app_config: AppConfig) -> None:
        """Should raise NSEFetchError when NSE is down."""
        responses.add(responses.GET, NSE_BASE_URL, status=503)

        from src.nse_client import NSEFetchError

        with pytest.raises(NSEFetchError):
            run_pipeline(app_config)

    @responses.activate
    @patch("src.main.get_utc_now", return_value=FIXED_TIMESTAMP)
    def test_github_upload_failure(
        self, mock_time: object, app_config: AppConfig
    ) -> None:
        """Should raise GitHubAPIError when upload fails."""
        _setup_nse_mocks(app_config)
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


class TestUpdateLog:
    """Test the log update step."""

    @responses.activate
    def test_update_log_success(self, app_config: AppConfig) -> None:
        """Should fetch, update, and push log.json."""
        _setup_github_get(app_config, "log.json", None)  # New log
        _setup_github_put(app_config, "log.json")

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
        # Simulate a connection error by not adding any mocks
        responses.add(
            responses.GET,
            f"{app_config.github_api_url}/log.json",
            json={"message": "Server Error"},
            status=500,
        )

        result = PipelineResult(RunStatus.ERROR, "test")
        # Should NOT raise even though GitHub API fails
        update_log(app_config, result, duration_ms=1000)
