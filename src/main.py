"""
Main orchestrator for the NSE Pre-Open Data Archiver.

Pipeline:
  1. Fetch NSE data (with session cookies + retries)
  2. Gzip + SHA256
  3. Build filename
  4. Fetch index.json from GitHub (fail-soft if missing)
  5. Check for duplicate hash
  6. If duplicate → log "skip" → exit 0
  7. If new → upload .gz → update index.json → update log.json → exit 0
  8. On error → log error → exit 1
"""

from __future__ import annotations

import logging
import sys
import time
from typing import NoReturn, Optional

from src.config import AppConfig, ConfigError
from src.nse_client import NSEClient, NSEFetchError
from src.compression import gzip_compress, sha256_hex, build_filename, get_utc_now
from src.github_repo import GitHubRepoClient, GitHubAPIError
from src.index_manager import (
    load_index,
    hash_exists,
    append_entry,
    serialize_index,
    count_records,
)
from src.log_manager import (
    load_log,
    append_run,
    serialize_log,
    RunStatus,
)

# ─── Logging Setup ───────────────────────────────────────────────────────────

LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-20s | %(message)s"
)


def setup_logging() -> None:
    """Configure structured logging to stdout (for GitHub Actions)."""
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt="%Y-%m-%dT%H:%M:%SZ",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    # Reduce noise from urllib3
    logging.getLogger("urllib3").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)


# ─── Pipeline Result ─────────────────────────────────────────────────────────

class PipelineResult:
    """Encapsulates the outcome of a pipeline run."""

    def __init__(
        self,
        status: RunStatus,
        message: str,
        filename: str | None = None,
        error_detail: str | None = None,
    ) -> None:
        self.status = status
        self.message = message
        self.filename = filename
        self.error_detail = error_detail

    @property
    def is_error(self) -> bool:
        return self.status == RunStatus.ERROR


# ─── Pipeline Class ──────────────────────────────────────────────────────────

class NSEArchiverPipeline:
    """
    Encapsulates the archival pipeline logic.
    """

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def fetch_data(self) -> bytes:
        """Step 1: Fetch raw data from NSE."""
        logger.info("=" * 60)
        logger.info("STEP 1: Fetching NSE pre-open data")
        logger.info("=" * 60)

        with NSEClient(self.config) as nse:
            raw_data = nse.fetch()

        logger.info("Fetched %d bytes of raw data", len(raw_data))
        return raw_data

    def process_data(self, raw_data: bytes) -> tuple[bytes, str]:
        """Step 2: Compress and hash the data."""
        logger.info("=" * 60)
        logger.info("STEP 2: Compressing and hashing")
        logger.info("=" * 60)

        compressed = gzip_compress(raw_data)
        data_hash = sha256_hex(compressed)

        logger.info(
            "Compressed: %d → %d bytes (%.1f%% reduction)",
            len(raw_data),
            len(compressed),
            (1 - len(compressed) / len(raw_data)) * 100,
        )
        logger.info("SHA-256: %s", data_hash)
        return compressed, data_hash

    def run(self) -> PipelineResult:
        """Execute the full pipeline."""
        now = get_utc_now()

        try:
            raw_data = self.fetch_data()
            compressed, data_hash = self.process_data(raw_data)

            # Step 3: Build filename
            filename = build_filename(now, data_hash)
            filepath = f"{self.config.data_dir}/{filename}"
            logger.info("Target file: %s", filepath)

            # Step 4: Interact with GitHub (Check duplicate -> Upload -> Update Index)
            return self._handle_github_operations(
                now, raw_data, compressed, data_hash, filename, filepath
            )

        except (NSEFetchError, GitHubAPIError) as exc:
            logger.error("Pipeline failed: %s", exc)
            return PipelineResult(
                status=RunStatus.ERROR,
                message=str(exc),
                error_detail=f"{type(exc).__name__}: {exc}",
            )
        except Exception as exc:
            logger.exception("Unexpected error in pipeline")
            return PipelineResult(
                status=RunStatus.ERROR,
                message=f"Unexpected error: {exc}",
                error_detail=f"{type(exc).__name__}: {exc}",
            )

    def _handle_github_operations(
        self,
        now: datetime,
        raw_data: bytes,
        compressed: bytes,
        data_hash: str,
        filename: str,
        filepath: str,
    ) -> PipelineResult:
        """
        Steps 4-7: Check index, upload file if new, update index.
        """
        logger.info("=" * 60)
        logger.info("STEP 3: Checking for duplicates")
        logger.info("=" * 60)

        with GitHubRepoClient(self.config) as github:
            index_file = github.get_file(self.config.index_file)
            index_raw = index_file.content if index_file else None
            index_sha = index_file.sha if index_file else None

            index = load_index(index_raw)

            if hash_exists(index, data_hash):
                logger.info(
                    "DUPLICATE detected — hash %s… already in index. Skipping.",
                    data_hash[:12],
                )
                return PipelineResult(
                    status=RunStatus.DUPLICATE,
                    message=f"Duplicate data (hash={data_hash[:12]}…). Skipped upload.",
                )

            # Step 6: Upload .gz file
            logger.info("=" * 60)
            logger.info("STEP 4: Uploading data file")
            logger.info("=" * 60)

            github.put_file(
                path=filepath,
                content=compressed,
                message=f"archive: {filename}",
            )

            # Step 7: Update index.json
            logger.info("=" * 60)
            logger.info("STEP 5: Updating index.json")
            logger.info("=" * 60)

            records = count_records(raw_data)
            append_entry(
                index=index,
                filename=filename,
                hash_hex=data_hash,
                timestamp=now,
                size_bytes=len(compressed),
                raw_size_bytes=len(raw_data),
                records_count=records,
            )
            index_bytes = serialize_index(index)

            github.put_file(
                path=self.config.index_file,
                content=index_bytes,
                message=f"index: add {filename}",
                sha=index_sha,
            )

        return PipelineResult(
            status=RunStatus.SUCCESS,
            message=f"Archived {filename} ({len(compressed)} bytes, {records or '?'} records)",
            filename=filename,
        )


def update_log(
    config: AppConfig,
    result: PipelineResult,
    duration_ms: int,
) -> None:
    """
    Update the run log on GitHub.

    This is a separate step so that even if it fails, the main
    pipeline result is still returned.
    """
    try:
        with GitHubRepoClient(config) as github:
            log_file = github.get_file(config.log_file)
            log_raw = log_file.content if log_file else None
            log_sha = log_file.sha if log_file else None

            log = load_log(log_raw)
            append_run(
                log=log,
                status=result.status,
                message=result.message,
                duration_ms=duration_ms,
                filename=result.filename,
                error_detail=result.error_detail,
            )
            log_bytes = serialize_log(log)

            github.put_file(
                path=config.log_file,
                content=log_bytes,
                message=f"log: {result.status.value} run",
                sha=log_sha,
            )
    except Exception as exc:
        # Log update failure should NOT fail the whole pipeline
        logger.error("Failed to update run log: %s", exc)


def run_pipeline(config: AppConfig) -> PipelineResult:
    """
    Legacy wrapper for backward compatibility / existing tests.
    Delegates to NSEArchiverPipeline.
    """
    pipeline = NSEArchiverPipeline(config)
    return pipeline.run()


# ─── Entry Point ─────────────────────────────────────────────────────────────

def main() -> NoReturn:
    """Main entry point for the pipeline."""
    setup_logging()

    logger.info("=" * 60)
    logger.info("NSE Pre-Open Data Archiver — Starting")
    logger.info("=" * 60)

    start_time = time.monotonic()

    try:
        config = AppConfig.from_env()
        logger.info(
            "Config loaded: repo=%s branch=%s",
            config.github_repo,
            config.github_branch,
        )
    except ConfigError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    # Instantiate pipeline
    pipeline = NSEArchiverPipeline(config)
    result = pipeline.run()

    elapsed_ms = int((time.monotonic() - start_time) * 1000)

    # Update run log (best-effort)
    logger.info("=" * 60)
    logger.info("Updating run log")
    logger.info("=" * 60)
    update_log(config, result, elapsed_ms)

    # Final summary
    logger.info("=" * 60)
    logger.info("RESULT: %s", result.status.value.upper())
    logger.info("MESSAGE: %s", result.message)
    logger.info("DURATION: %d ms", elapsed_ms)
    logger.info("=" * 60)

    sys.exit(1 if result.is_error else 0)


if __name__ == "__main__":
    main()
