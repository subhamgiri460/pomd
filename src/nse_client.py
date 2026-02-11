"""
NSE HTTP client with session management, cookie handling, and retries.

NSE blocks direct API calls — you must first visit the homepage to get
session cookies, then hit the API endpoint. This module handles that
transparently.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from src.config import (
    NSE_BASE_URL,
    MIN_RESPONSE_BYTES,
    EXPECTED_CONTENT_TYPE,
)

if TYPE_CHECKING:
    from src.config import AppConfig

logger = logging.getLogger(__name__)


# ─── Exceptions ──────────────────────────────────────────────────────────────

class NSEFetchError(Exception):
    """Raised when NSE data cannot be fetched after all retries."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class NSEValidationError(NSEFetchError):
    """Raised when the NSE response fails validation checks."""


# ─── Client ──────────────────────────────────────────────────────────────────

class NSEClient:
    """
    HTTP client for fetching NSE pre-open market data.

    Usage:
        client = NSEClient(config)
        raw_bytes = client.fetch()
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._session = self._build_session()

    def _build_session(self) -> requests.Session:
        """Create a requests.Session with retry logic and proper headers."""
        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=self._config.max_retries,
            backoff_factor=self._config.retry_backoff,
            status_forcelist=list(self._config.RETRY_STATUS_CODES),
            allowed_methods=["GET"],
            raise_on_status=False,      # We handle status ourselves
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)

        # Set default headers
        session.headers.update(self._config.nse_headers)

        return session

    def _establish_session_cookies(self) -> None:
        """
        Hit the NSE homepage to get session cookies.

        NSE requires valid cookies (like nseappid, nsit, etc.) before
        allowing API access. Without this step, API calls return 401/403.
        """
        logger.info("Establishing NSE session cookies via homepage...")
        try:
            resp = self._session.get(
                NSE_BASE_URL,
                timeout=self._config.request_timeout,
            )
            resp.raise_for_status()
            cookie_names = list(self._session.cookies.keys())
            logger.info(
                "Session established. Cookies: %s",
                cookie_names or "(none — may still work)",
            )
        except requests.RequestException as exc:
            raise NSEFetchError(
                f"Failed to establish NSE session: {exc}"
            ) from exc

    def _validate_response(self, response: requests.Response) -> None:
        """
        Validate the HTTP response from NSE.

        Checks:
        1. HTTP status is 2xx
        2. Response body is non-empty and above minimum size
        3. Content-type looks like JSON
        4. Body parses as valid JSON
        """
        # Check HTTP status
        if not response.ok:
            raise NSEFetchError(
                f"NSE returned HTTP {response.status_code}: "
                f"{response.text[:200]}",
                status_code=response.status_code,
            )

        # Check body size
        body = response.content
        if len(body) < MIN_RESPONSE_BYTES:
            raise NSEValidationError(
                f"Response too small ({len(body)} bytes, "
                f"minimum {MIN_RESPONSE_BYTES}). "
                "NSE may have changed the API or returned an error page."
            )

        # Check content type (NSE sometimes returns text/html on errors)
        content_type = response.headers.get("Content-Type", "")
        if EXPECTED_CONTENT_TYPE not in content_type:
            # Log warning but don't fail — sometimes content-type is wrong
            # but the body is still valid JSON
            logger.warning(
                "Unexpected Content-Type: %s (expected %s). "
                "Proceeding with JSON parse check.",
                content_type,
                EXPECTED_CONTENT_TYPE,
            )

        # Try to parse as JSON to ensure the response is valid
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NSEValidationError(
                f"Response is not valid JSON: {exc}. "
                f"First 200 chars: {body[:200]!r}"
            ) from exc

        # Validate expected structure — NSE returns a dict with a "data" key
        if not isinstance(parsed, dict):
            raise NSEValidationError(
                f"Expected JSON object, got {type(parsed).__name__}. "
                "NSE may have changed the API response format."
            )

        logger.info(
            "Response validated: %d bytes, %d top-level keys",
            len(body),
            len(parsed),
        )

    def fetch(self) -> bytes:
        """
        Fetch pre-open market data from NSE.

        Returns:
            Raw response body as bytes (JSON).

        Raises:
            NSEFetchError: If the request fails after all retries.
            NSEValidationError: If the response fails validation.
        """
        # Step 1: Get session cookies
        self._establish_session_cookies()

        # Step 2: Fetch the actual data
        logger.info("Fetching NSE pre-open data from %s", self._config.nse_url)
        try:
            response = self._session.get(
                self._config.nse_url,
                timeout=self._config.request_timeout,
            )
        except requests.RequestException as exc:
            raise NSEFetchError(
                f"HTTP request failed after retries: {exc}"
            ) from exc

        # Step 3: Validate the response
        self._validate_response(response)

        logger.info(
            "Successfully fetched %d bytes from NSE",
            len(response.content),
        )
        return response.content

    def close(self) -> None:
        """Close the underlying HTTP session."""
        self._session.close()

    def __enter__(self) -> NSEClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
