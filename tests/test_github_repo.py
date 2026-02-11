"""Tests for src.github_repo — GitHub Contents API client."""

from __future__ import annotations

import base64
import json

import pytest
import responses

from src.config import AppConfig
from src.github_repo import GitHubRepoClient, GitHubAPIError, FileContent


@pytest.fixture
def github_client(app_config: AppConfig) -> GitHubRepoClient:
    """Create a GitHubRepoClient for testing."""
    return GitHubRepoClient(app_config)


def _api_url(app_config: AppConfig, path: str) -> str:
    """Build the expected API URL for a path."""
    return f"{app_config.github_api_url}/{path}"


class TestGetFile:
    """Test GitHub file retrieval."""

    @responses.activate
    def test_get_existing_file(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should return FileContent for existing files."""
        content = b'{"files": []}'
        b64_content = base64.b64encode(content).decode()

        responses.add(
            responses.GET,
            _api_url(app_config, "index.json"),
            json={
                "content": b64_content,
                "sha": "abc123sha",
                "path": "index.json",
            },
            status=200,
        )

        result = github_client.get_file("index.json")
        assert result is not None
        assert result.content == content
        assert result.sha == "abc123sha"

    @responses.activate
    def test_get_missing_file_returns_none(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should return None for 404 (file not found)."""
        responses.add(
            responses.GET,
            _api_url(app_config, "index.json"),
            json={"message": "Not Found"},
            status=404,
        )

        result = github_client.get_file("index.json")
        assert result is None

    @responses.activate
    def test_get_file_server_error_raises(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should raise GitHubAPIError on server errors."""
        responses.add(
            responses.GET,
            _api_url(app_config, "index.json"),
            json={"message": "Internal Server Error"},
            status=500,
        )

        with pytest.raises(GitHubAPIError, match="HTTP 500"):
            github_client.get_file("index.json")

    @responses.activate
    def test_get_file_strips_leading_slash(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should handle paths with leading slash."""
        content = b"test"
        responses.add(
            responses.GET,
            _api_url(app_config, "path/to/file"),
            json={
                "content": base64.b64encode(content).decode(),
                "sha": "sha123",
            },
            status=200,
        )

        result = github_client.get_file("/path/to/file")
        assert result is not None
        assert result.content == content


class TestPutFile:
    """Test GitHub file creation/update."""

    @responses.activate
    def test_create_new_file(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should create file without SHA (new file)."""
        responses.add(
            responses.PUT,
            _api_url(app_config, "data/test.gz"),
            json={"commit": {"sha": "newcommit123"}},
            status=201,
        )

        commit_sha = github_client.put_file(
            path="data/test.gz",
            content=b"compressed data",
            message="archive: test.gz",
        )

        assert commit_sha == "newcommit123"
        # Verify request body
        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["message"] == "archive: test.gz"
        assert "sha" not in request_body  # No SHA for new files

    @responses.activate
    def test_update_existing_file(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should include SHA when updating existing file."""
        responses.add(
            responses.PUT,
            _api_url(app_config, "index.json"),
            json={"commit": {"sha": "updatecommit456"}},
            status=200,
        )

        github_client.put_file(
            path="index.json",
            content=b'{"files": []}',
            message="index: update",
            sha="existing_sha_789",
        )

        request_body = json.loads(responses.calls[0].request.body)
        assert request_body["sha"] == "existing_sha_789"

    @responses.activate
    def test_put_file_error_raises(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should raise GitHubAPIError on failure."""
        responses.add(
            responses.PUT,
            _api_url(app_config, "data/test.gz"),
            json={"message": "Conflict"},
            status=409,
        )

        with pytest.raises(GitHubAPIError, match="HTTP 409"):
            github_client.put_file(
                path="data/test.gz",
                content=b"data",
                message="test",
            )

    @responses.activate
    def test_put_file_uses_base64_encoding(
        self, github_client: GitHubRepoClient, app_config: AppConfig
    ) -> None:
        """Should base64-encode the content in the request."""
        content = b"binary data with \x00 null bytes"
        responses.add(
            responses.PUT,
            _api_url(app_config, "test.bin"),
            json={"commit": {"sha": "abc"}},
            status=201,
        )

        github_client.put_file("test.bin", content, "test commit")

        request_body = json.loads(responses.calls[0].request.body)
        decoded = base64.b64decode(request_body["content"])
        assert decoded == content


class TestContextManager:
    """Test context manager behavior."""

    def test_context_manager(self, app_config: AppConfig) -> None:
        """Should support context manager protocol."""
        with GitHubRepoClient(app_config) as client:
            assert client is not None
