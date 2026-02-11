"""
GitHub Repository client using the GitHub Contents API.

Handles fetching and uploading files via the REST API. Uses base64
encoding as required by the GitHub Contents API.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)


# ─── Exceptions ──────────────────────────────────────────────────────────────

class GitHubAPIError(Exception):
    """Raised when a GitHub API call fails."""

    def __init__(
        self, message: str, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.status_code = status_code


# ─── Data Types ──────────────────────────────────────────────────────────────

@dataclass
class FileContent:
    """Represents a file fetched from GitHub."""
    content: bytes
    sha: str                # Git blob SHA — needed for updates
    path: str


# ─── Client ──────────────────────────────────────────────────────────────────

class GitHubRepoClient:
    """
    Client for GitHub Contents API operations.

    Supports:
    - get_file: Fetch a file's content and SHA
    - put_file: Create or update a file
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._api_url = config.github_api_url
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        session = requests.Session()

        # Configure retries for resilience
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "PUT", "POST"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        session.headers.update({
            "Accept": "application/vnd.github.v3+json",
            "Authorization": f"Bearer {self._config.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "NSE-Archiver-Bot/1.0",
        })
        return session

    def _url_for(self, path: str) -> str:
        """Build the full API URL for a file path."""
        # Remove leading slash if present
        path = path.lstrip("/")
        return f"{self._api_url}/{path}"

    def get_file(self, path: str) -> FileContent | None:
        """
        Fetch a file from the repository.

        Args:
            path: Repository-relative file path (e.g., "index.json").

        Returns:
            FileContent with decoded bytes and SHA, or None if not found (404).

        Raises:
            GitHubAPIError: On non-404 errors.
        """
        url = self._url_for(path)
        params = {"ref": self._config.github_branch}

        logger.info("Fetching file from GitHub: %s", path)
        try:
            resp = self._session.get(url, params=params, timeout=30)
        except requests.RequestException as exc:
            raise GitHubAPIError(
                f"Failed to fetch {path}: {exc}"
            ) from exc

        if resp.status_code == 404:
            logger.info("File not found: %s (will create)", path)
            return None

        if not resp.ok:
            raise GitHubAPIError(
                f"GitHub API error fetching {path}: "
                f"HTTP {resp.status_code} — {resp.text[:300]}",
                status_code=resp.status_code,
            )

        data = resp.json()
        content_b64 = data.get("content", "")
        sha = data.get("sha", "")

        # GitHub returns base64 with newlines; strip them
        content_bytes = base64.b64decode(content_b64)

        logger.info(
            "Fetched %s (%d bytes, sha=%s…)",
            path,
            len(content_bytes),
            sha[:8],
        )
        return FileContent(content=content_bytes, sha=sha, path=path)

    def put_file(
        self,
        path: str,
        content: bytes,
        message: str,
        sha: str | None = None,
    ) -> str:
        """
        Create or update a file in the repository.

        Args:
            path: Repository-relative file path.
            content: Raw bytes to upload.
            message: Commit message.
            sha: Existing file SHA (required for updates, omit for creates).

        Returns:
            The new commit SHA.

        Raises:
            GitHubAPIError: On API errors.
        """
        url = self._url_for(path)

        payload: dict = {
            "message": message,
            "content": base64.b64encode(content).decode("ascii"),
            "branch": self._config.github_branch,
            "committer": {
                "name": self._config.commit_author_name,
                "email": self._config.commit_author_email,
            },
        }
        if sha is not None:
            payload["sha"] = sha

        action = "Updating" if sha else "Creating"
        logger.info("%s file on GitHub: %s", action, path)

        try:
            resp = self._session.put(url, json=payload, timeout=30)
        except requests.RequestException as exc:
            raise GitHubAPIError(
                f"Failed to {action.lower()} {path}: {exc}"
            ) from exc

        if not resp.ok:
            raise GitHubAPIError(
                f"GitHub API error {action.lower()} {path}: "
                f"HTTP {resp.status_code} — {resp.text[:300]}",
                status_code=resp.status_code,
            )

        result = resp.json()
        commit_sha = result.get("commit", {}).get("sha", "unknown")
        logger.info(
            "Successfully %s %s (commit: %s…)",
            action.lower().rstrip("e") + "ed",  # Creating→created
            path,
            commit_sha[:8],
        )
        return commit_sha

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> GitHubRepoClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
