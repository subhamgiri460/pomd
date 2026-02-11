"""
Structured run log manager.

Maintains a log.json file with an array of run entries. Each entry
records the outcome of a pipeline run (success, duplicate, error).
Log is capped at MAX_LOG_ENTRIES to prevent unbounded growth.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.config import MAX_LOG_ENTRIES

logger = logging.getLogger(__name__)


class RunStatus(str, Enum):
    """Possible outcomes of a pipeline run."""
    SUCCESS = "success"
    DUPLICATE = "duplicate"
    ERROR = "error"


def _make_run_entry(
    status: RunStatus,
    message: str,
    duration_ms: int,
    filename: str | None = None,
    error_detail: str | None = None,
    failed_step: str | None = None,
) -> dict[str, Any]:
    """Build a single run log entry."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": status.value,
        "message": message,
        "duration_ms": duration_ms,
    }
    if filename:
        entry["filename"] = filename
    if error_detail:
        entry["error_detail"] = error_detail
    if failed_step:
        entry["failed_step"] = failed_step
    return entry


def load_log(raw: bytes | None) -> dict[str, Any]:
    """
    Parse raw log.json bytes into a dict.

    Returns default structure if raw is None or invalid.

    Args:
        raw: Raw bytes of log.json, or None.

    Returns:
        Log dict with "runs" array.
    """
    default: dict[str, Any] = {"version": 1, "runs": [], "total_runs": 0}

    if raw is None:
        logger.info("No existing log.json — initializing empty log")
        return default

    try:
        log = json.loads(raw)
        if "runs" not in log:
            log["runs"] = []
        return log
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning("Failed to parse log.json (%s). Starting fresh.", exc)
        return default


def append_run(
    log: dict[str, Any],
    status: RunStatus,
    message: str,
    duration_ms: int,
    filename: str | None = None,
    error_detail: str | None = None,
    failed_step: str | None = None,
) -> dict[str, Any]:
    """
    Append a run entry to the log and enforce the cap.

    Args:
        log: Parsed log dict (modified in place AND returned).
        status: Run outcome.
        message: Human-readable summary.
        duration_ms: Total run duration in milliseconds.
        filename: Uploaded filename (for success runs).
        error_detail: Error details (for error runs).
        failed_step: The pipeline step where the failure occurred.

    Returns:
        Updated log dict.
    """
    entry = _make_run_entry(
        status=status,
        message=message,
        duration_ms=duration_ms,
        filename=filename,
        error_detail=error_detail,
        failed_step=failed_step,
    )
    log["runs"].append(entry)

    # Enforce cap — keep only the most recent entries
    if len(log["runs"]) > MAX_LOG_ENTRIES:
        overflow = len(log["runs"]) - MAX_LOG_ENTRIES
        log["runs"] = log["runs"][overflow:]
        logger.info("Log rotation: removed %d old entries", overflow)

    log["total_runs"] = log.get("total_runs", 0) + 1
    return log


def serialize_log(log: dict[str, Any]) -> bytes:
    """
    Serialize the log to pretty-printed JSON bytes.

    Returns:
        UTF-8 encoded JSON bytes with 2-space indentation.
    """
    return json.dumps(
        log, indent=2, ensure_ascii=False, sort_keys=False
    ).encode("utf-8")
