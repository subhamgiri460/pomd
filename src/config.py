"""
Centralized configuration for the NSE Pre-Open Data Archiver.

All tunables, constants, and environment variable loading live here.
To adapt to NSE changes (new UA, different endpoint, etc.), edit ONLY this file.
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ─── Exceptions ──────────────────────────────────────────────────────────────

class ConfigError(Exception):
    """Raised when a required configuration value is missing or invalid."""


# ─── Constants (never change at runtime) ─────────────────────────────────────

# NSE endpoint — update here if NSE changes the URL
NSE_BASE_URL = "https://www.nseindia.com"
NSE_API_PATH = "/api/market-data-pre-open"
NSE_API_QUERY = "key=ALL&selectValFormat=crores"
NSE_API_URL = f"{NSE_BASE_URL}{NSE_API_PATH}?{NSE_API_QUERY}"

# Referer — simple base domain works with curl
NSE_REFERER = "https://www.nseindia.com/"

# User-Agent — matches the curl command that works against NSE
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"

# Accept header
DEFAULT_ACCEPT = "application/json"

# HTTP tuning (used by curl subprocess)
DEFAULT_REQUEST_TIMEOUT: int = 30        # seconds per request (--max-time)
DEFAULT_MAX_RETRIES: int = 3             # curl --retry count
DEFAULT_RETRY_DELAY: int = 2             # curl --retry-delay seconds

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
    retry_delay: int = DEFAULT_RETRY_DELAY
    data_dir: str = DEFAULT_DATA_DIR
    index_file: str = DEFAULT_INDEX_FILE
    log_file: str = DEFAULT_LOG_FILE
    commit_author_name: str = DEFAULT_COMMIT_AUTHOR_NAME
    commit_author_email: str = DEFAULT_COMMIT_AUTHOR_EMAIL

    # Derived — computed at init
    github_api_url: str = field(init=False)
    nse_headers: dict[str, str] = field(init=False)

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
            "Referer": NSE_REFERER,
            "Connection": "keep-alive",
        }
        object.__setattr__(self, "nse_headers", headers)

    @classmethod
    def from_env(cls) -> AppConfig:
        """
        Load configuration from environment variables.

        Prioritizes TARGET_GITHUB_TOKEN and TARGET_GITHUB_REPO if set.
        Otherwise falls back to GITHUB_TOKEN and GITHUB_REPO.

        Required env vars (one of):
            TARGET_GITHUB_TOKEN (or GITHUB_TOKEN)
            TARGET_GITHUB_REPO  (or GITHUB_REPO)

        Optional env vars (with defaults):
            GITHUB_BRANCH, NSE_URL, USER_AGENT, REQUEST_TIMEOUT,
            MAX_RETRIES, RETRY_BACKOFF, DATA_DIR, INDEX_FILE, LOG_FILE,
            COMMIT_AUTHOR_NAME, COMMIT_AUTHOR_EMAIL
        """
        token = os.environ.get("TARGET_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        repo = os.environ.get("TARGET_GITHUB_REPO") or os.environ.get("GITHUB_REPO", "")

        if not token:
            raise ConfigError(
                "Environment variable TARGET_GITHUB_TOKEN (or GITHUB_TOKEN) is not set."
            )
        if not repo:
            raise ConfigError(
                "Environment variable TARGET_GITHUB_REPO (or GITHUB_REPO) is not set."
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
            retry_delay=int(
                os.environ.get("RETRY_DELAY", str(DEFAULT_RETRY_DELAY))
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
