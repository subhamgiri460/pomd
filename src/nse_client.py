"""
NSE HTTP client using curl subprocess.

Uses the exact curl approach that is proven to work against NSE's WAF.
No cookie initialization needed — curl with the right headers and HTTP/1.1
bypasses NSE's bot detection that blocks Python requests.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import TYPE_CHECKING, Any

from src.config import MIN_RESPONSE_BYTES

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
    HTTP client for fetching NSE pre-open market data via curl.

    Uses subprocess to invoke curl with the exact flags that bypass
    NSE's bot detection. This matches the proven working curl command:

        curl --http1.1 -L \\
          -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64)" \\
          -H "Accept: application/json" \\
          -H "Referer: https://www.nseindia.com/" \\
          -H "Connection: keep-alive" \\
          --compressed \\
          "https://www.nseindia.com/api/market-data-pre-open?key=ALL&selectValFormat=crores"

    Usage:
        client = NSEClient(config)
        raw_bytes = client.fetch()
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._curl_path = self._find_curl()

    @staticmethod
    def _find_curl() -> str:
        """Locate the curl binary or raise an error."""
        curl = shutil.which("curl")
        if not curl:
            raise NSEFetchError(
                "curl is not installed or not found in PATH. "
                "Install curl (apt-get install curl) and retry."
            )
        return curl

    def _get_curl_command(self, output_file: str) -> list[str]:
        """
        Build the curl command line.

        Writes the response body to `output_file` and prints the
        HTTP status code to stdout.
        """
        headers = self._config.nse_headers
        cmd = [
            self._curl_path,
            "--http1.1",           # Force HTTP/1.1 (critical for NSE)
            "-L",                  # Follow redirects
            "--compressed",        # Accept-Encoding: gzip,deflate + auto-decompress
            "-s", "-S",            # Silent but show errors
            "-o", output_file,     # Write body to temp file
            "-w", "%{http_code}",  # Print HTTP status code to stdout
            "--max-time", str(self._config.request_timeout),
            "--retry", str(self._config.max_retries),
            "--retry-delay", str(self._config.retry_delay),
            "--retry-all-errors",  # Retry on all errors, not just transient
        ]

        # Add headers from config
        for name, value in headers.items():
            cmd.extend(["-H", f"{name}: {value}"])

        # URL must be last
        cmd.append(self._config.nse_url)

        return cmd

    def _execute_curl(self, cmd: list[str]) -> int:
        """
        Execute the curl command and return the HTTP status code.

        Raises:
            NSEFetchError: On execution failure, timeout, or non-integer status output.
        """
        logger.info("Fetching NSE data via curl: %s", self._config.nse_url)
        logger.debug("curl command: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._config.request_timeout + 10,  # extra buffer
            )
        except subprocess.TimeoutExpired as exc:
            raise NSEFetchError(
                f"curl timed out after {self._config.request_timeout + 10}s"
            ) from exc
        except FileNotFoundError as exc:
            raise NSEFetchError(
                "curl binary not found. Is curl installed?"
            ) from exc

        # Parse HTTP status code from stdout
        status_str = result.stdout.strip()
        stderr_output = result.stderr.strip()

        if result.returncode != 0:
            raise NSEFetchError(
                f"curl failed (exit code {result.returncode}): "
                f"{stderr_output or 'no error output'}",
                status_code=int(status_str) if status_str.isdigit() else None,
            )

        if not status_str.isdigit():
            raise NSEFetchError(
                f"Could not parse HTTP status from curl output: "
                f"{status_str!r}. Stderr: {stderr_output}"
            )

        return int(status_str)

    def _read_file(self, filepath: str) -> bytes:
        """Read the content of the temporary output file."""
        try:
            with open(filepath, "rb") as f:
                return f.read()
        except FileNotFoundError:
            # Caller handles context
            raise

    def _validate_response(self, body: bytes) -> None:
        """
        Validate the response body from NSE.

        Checks:
        1. Response body is non-empty and above minimum size
        2. Body parses as valid JSON
        3. JSON is a dict (expected NSE structure)
        4. JSON contains 'data' key (core payload)
        """
        # Check body size
        if len(body) < MIN_RESPONSE_BYTES:
            raise NSEValidationError(
                f"Response too small ({len(body)} bytes, "
                f"minimum {MIN_RESPONSE_BYTES}). "
                "NSE may have changed the API or returned an error page."
            )

        # Try to parse as JSON
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise NSEValidationError(
                f"Response is not valid JSON: {exc}. "
                f"First 200 chars: {body[:200]!r}"
            ) from exc

        # Validate expected structure — NSE returns a dict
        if not isinstance(parsed, dict):
            raise NSEValidationError(
                f"Expected JSON object, got {type(parsed).__name__}. "
                "NSE may have changed the API response format."
            )

        if not parsed:
            raise NSEValidationError(
                "Response JSON object is empty. NSE returned {}."
            )

        # Specific check for 'data' key based on API analysis
        if "data" not in parsed:
             raise NSEValidationError(
                "Response JSON missing 'data' key. NSE may have changed API format."
            )

        logger.info(
            "Response validated: %d bytes, %d top-level keys",
            len(body),
            len(parsed),
        )

    def fetch(self) -> bytes:
        """
        Fetch pre-open market data from NSE using curl.

        Returns:
            Raw response body as bytes (JSON).

        Raises:
            NSEFetchError: If curl fails or returns non-2xx status.
            NSEValidationError: If the response fails validation.
        """
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_file = os.path.join(tmp_dir, "response.json")
            cmd = self._get_curl_command(output_file)

            status_code = self._execute_curl(cmd)

            if status_code < 200 or status_code >= 300:
                raise NSEFetchError(
                    f"NSE returned HTTP {status_code}",
                    status_code=status_code,
                )

            # Read response body from temp file
            try:
                body = self._read_file(output_file)
            except FileNotFoundError:
                 # Re-raising with context if needed, but here simple catch is enough
                 # as we don't have stderr easily available in this scope without
                 # redesigning _execute_curl to return it.
                 # However, _execute_curl raises if returncode != 0, so this usually
                 # implies curl claimed success but didn't write file.
                 raise NSEFetchError(
                    f"Output file not found after curl run (HTTP {status_code}). "
                    "curl may have failed silently."
                )

            if not body:
                raise NSEFetchError(
                    f"Empty response body (HTTP {status_code}). "
                    "curl may have failed silently."
                )

            logger.info(
                "curl returned HTTP %d, %d bytes", status_code, len(body)
            )

        # Validate the response
        self._validate_response(body)

        logger.info("Successfully fetched %d bytes from NSE", len(body))
        return body

    def close(self) -> None:
        """No-op — curl subprocess is stateless."""

    def __enter__(self) -> NSEClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
