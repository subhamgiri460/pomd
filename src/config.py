"""
Centralized configuration for the NSE Pre-Open Data Archiver.

All tunables, constants, and environment variable loading live here.
To adapt to NSE changes (new UA, different endpoint, etc.), edit ONLY this file.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field
from typing import ClassVar

logger = logging.getLogger(__name__)


# ─── Exceptions ──────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when a required configuration value is missing or invalid."""


# ─── Constants (never change at runtime) ─────────────────────────────────────

# NSE endpoint — update here if NSE changes the URL
NSE_BASE_URL = "https://www.nseindia.com"
NSE_API_PATH = "/api/market-data-pre-open"
NSE_API_URL = f"{NSE_BASE_URL}{NSE_API_PATH}"

# Referer must match a real NSE page that uses this API
NSE_REFERER = (
    "https://www.nseindia.com/market-data/pre-open-market-cm-and-emerge-market"
)

# User-Agent — must look like a real browser; update when NSE blocks it
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# Accept headers NSE expects
DEFAULT_ACCEPT = "application/json, text/plain, */*"
DEFAULT_ACCEPT_LANGUAGE = "en-US,en;q=0.9"
DEFAULT_ACCEPT_ENCODING = "gzip, deflate, br"

# HTTP tuning
DEFAULT_REQUEST_TIMEOUT: int = 30        # seconds per request
DEFAULT_MAX_RETRIES: int = 3             # total retry attempts
DEFAULT_RETRY_BACKOFF: float = 2.0       # exponential backoff multiplier
DEFAULT_RETRY_STATUS_CODES: tuple[int, ...] = (429, 500, 502, 503, 504)

# File naming
FILENAME_PREFIX = "preopen"
FILENAME_EXTENSION = ".json.gz"
TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"     # ISO-8601 compact UTC

# Repository paths
DEFAULT_DATA_DIR = "data"
DEFAULT_INDEX_FILE = "index.json"
DEFAULT_LOG_FILE = "log.json"

# Log rotation
MAX_LOG_ENTRIES: int = 500

# Git commit defaults
DEFAULT_COMMIT_AUTHOR_NAME = "NSE Archiver Bot"
DEFAULT_COMMIT_AUTHOR_EMAIL = "bot@nse-archiver.local"
DEFAULT_BRANCH = "main"

# GitHub API
GITHUB_API_BASE = "https://api.github.com"

# Response validation
MIN_RESPONSE_BYTES: int = 100            # NSE response must be at least this big
EXPECTED_CONTENT_TYPE = "application/json"


# ─── Runtime Config (loaded from env) ────────────────────────────────────────

@dataclass(frozen=True)
class AppConfig:
    """
    Immutable runtime configuration. Loaded once from environment variables
    at startup. Use `AppConfig.from_env()` to create.
    """

    # Required — must come from environment
    github_token: str
    github_repo: str                       # "owner/repo"

    # Optional — have sensible defaults
    github_branch: str = DEFAULT_BRANCH
    nse_url: str = NSE_API_URL
    user_agent: str = DEFAULT_USER_AGENT
    request_timeout: int = DEFAULT_REQUEST_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    data_dir: str = DEFAULT_DATA_DIR
    index_file: str = DEFAULT_INDEX_FILE
    log_file: str = DEFAULT_LOG_FILE
    commit_author_name: str = DEFAULT_COMMIT_AUTHOR_NAME
    commit_author_email: str = DEFAULT_COMMIT_AUTHOR_EMAIL

    # Derived — computed at init
    github_api_url: str = field(init=False)
    nse_headers: dict[str, str] = field(init=False)

    # Class-level constants exposed for tests
    RETRY_STATUS_CODES: ClassVar[tuple[int, ...]] = DEFAULT_RETRY_STATUS_CODES

    def __post_init__(self) -> None:
        # Validate required fields
        if not self.github_token:
            raise ConfigError("GITHUB_TOKEN is required but empty")
        if not self.github_repo or "/" not in self.github_repo:
            raise ConfigError(
                f"GITHUB_REPO must be 'owner/repo', got: {self.github_repo!r}"
            )

        # Compute derived fields (frozen=True requires object.__setattr__)
        api_url = f"{GITHUB_API_BASE}/repos/{self.github_repo}/contents"
        object.__setattr__(self, "github_api_url", api_url)

        headers = {
            "User-Agent": self.user_agent,
            "Accept": DEFAULT_ACCEPT,
            "Accept-Language": DEFAULT_ACCEPT_LANGUAGE,
            "Accept-Encoding": DEFAULT_ACCEPT_ENCODING,
            "Referer": NSE_REFERER,
        }
        object.__setattr__(self, "nse_headers", headers)

    @classmethod
    def from_env(cls) -> AppConfig:
        """
        Load configuration from environment variables.

        Required env vars:
            GITHUB_TOKEN  — Personal access token with repo scope
            GITHUB_REPO   — Target repository as "owner/repo"

        Optional env vars (with defaults):
            GITHUB_BRANCH, NSE_URL, USER_AGENT, REQUEST_TIMEOUT,
            MAX_RETRIES, RETRY_BACKOFF, DATA_DIR, INDEX_FILE, LOG_FILE,
            COMMIT_AUTHOR_NAME, COMMIT_AUTHOR_EMAIL
        """
        token = os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("GITHUB_REPO", "")

        if not token:
            raise ConfigError(
                "Environment variable GITHUB_TOKEN is not set. "
                "Set it to a GitHub PAT with 'repo' scope."
            )
        if not repo:
            raise ConfigError(
                "Environment variable GITHUB_REPO is not set. "
                "Set it to 'owner/repo' format."
            )

        return cls(
            github_token=token,
            github_repo=repo,
            github_branch=os.environ.get("GITHUB_BRANCH", DEFAULT_BRANCH),
            nse_url=os.environ.get("NSE_URL", NSE_API_URL),
            user_agent=os.environ.get("USER_AGENT", DEFAULT_USER_AGENT),
            request_timeout=int(
                os.environ.get("REQUEST_TIMEOUT", str(DEFAULT_REQUEST_TIMEOUT))
            ),
            max_retries=int(
                os.environ.get("MAX_RETRIES", str(DEFAULT_MAX_RETRIES))
            ),
            retry_backoff=float(
                os.environ.get("RETRY_BACKOFF", str(DEFAULT_RETRY_BACKOFF))
            ),
            data_dir=os.environ.get("DATA_DIR", DEFAULT_DATA_DIR),
            index_file=os.environ.get("INDEX_FILE", DEFAULT_INDEX_FILE),
            log_file=os.environ.get("LOG_FILE", DEFAULT_LOG_FILE),
            commit_author_name=os.environ.get(
                "COMMIT_AUTHOR_NAME", DEFAULT_COMMIT_AUTHOR_NAME
            ),
            commit_author_email=os.environ.get(
                "COMMIT_AUTHOR_EMAIL", DEFAULT_COMMIT_AUTHOR_EMAIL
            ),
        )
