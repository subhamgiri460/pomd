"""Tests for src.log_manager — structured run log management."""

from __future__ import annotations

import json

import pytest

from src.log_manager import (
    load_log,
    append_run,
    serialize_log,
    RunStatus,
)
from src.config import MAX_LOG_ENTRIES


class TestLoadLog:
    """Test log loading and fail-soft behavior."""

    def test_load_none_returns_default(self) -> None:
        """Should return empty log when file is missing."""
        log = load_log(None)
        assert log["runs"] == []
        assert log["version"] == 1
        assert log["total_runs"] == 0

    def test_load_valid_log(self) -> None:
        """Should parse valid log.json."""
        data = {
            "version": 1,
            "runs": [
                {
                    "timestamp": "2026-02-10T03:38:00Z",
                    "status": "success",
                    "message": "Archived file",
                    "duration_ms": 5000,
                }
            ],
            "total_runs": 1,
        }
        raw = json.dumps(data).encode()
        log = load_log(raw)
        assert len(log["runs"]) == 1
        assert log["runs"][0]["status"] == "success"

    def test_load_invalid_json_returns_default(self) -> None:
        """Should return default on invalid JSON."""
        log = load_log(b"corrupted{{{")
        assert log["runs"] == []

    def test_load_missing_runs_key(self) -> None:
        """Should add missing 'runs' key."""
        raw = json.dumps({"version": 1}).encode()
        log = load_log(raw)
        assert "runs" in log
        assert isinstance(log["runs"], list)


class TestAppendRun:
    """Test appending run entries."""

    def test_append_success_run(self) -> None:
        """Should add a success entry."""
        log = load_log(None)

        append_run(
            log=log,
            status=RunStatus.SUCCESS,
            message="Archived preopen_test.json.gz",
            duration_ms=4500,
            filename="preopen_test.json.gz",
        )

        assert len(log["runs"]) == 1
        entry = log["runs"][0]
        assert entry["status"] == "success"
        assert entry["filename"] == "preopen_test.json.gz"
        assert entry["duration_ms"] == 4500
        assert "timestamp" in entry

    def test_append_duplicate_run(self) -> None:
        """Should add a duplicate detection entry."""
        log = load_log(None)

        append_run(
            log=log,
            status=RunStatus.DUPLICATE,
            message="Duplicate data, skipped",
            duration_ms=3000,
        )

        assert log["runs"][0]["status"] == "duplicate"
        assert "filename" not in log["runs"][0]

    def test_append_error_run(self) -> None:
        """Should add an error entry with detail and failed_step."""
        log = load_log(None)

        append_run(
            log=log,
            status=RunStatus.ERROR,
            message="Failed to fetch NSE data",
            duration_ms=10000,
            error_detail="NSEFetchError: Connection timeout",
            failed_step="fetching_data",
        )

        entry = log["runs"][0]
        assert entry["status"] == "error"
        assert entry["error_detail"] == "NSEFetchError: Connection timeout"
        assert entry["failed_step"] == "fetching_data"

    def test_total_runs_increments(self) -> None:
        """total_runs should increment with each append."""
        log = load_log(None)

        for i in range(5):
            append_run(log, RunStatus.SUCCESS, f"Run {i}", 1000)

        assert log["total_runs"] == 5

    def test_log_cap_enforced(self) -> None:
        """Log should be capped at MAX_LOG_ENTRIES."""
        log = load_log(None)

        # Add more than MAX_LOG_ENTRIES
        for i in range(MAX_LOG_ENTRIES + 50):
            append_run(log, RunStatus.SUCCESS, f"Run {i}", 1000)

        assert len(log["runs"]) == MAX_LOG_ENTRIES
        # Most recent entries should be kept
        last_entry = log["runs"][-1]
        assert last_entry["message"] == f"Run {MAX_LOG_ENTRIES + 49}"

    def test_log_cap_keeps_recent(self) -> None:
        """After rotation, oldest entries should be removed."""
        log = load_log(None)

        for i in range(MAX_LOG_ENTRIES + 10):
            append_run(log, RunStatus.SUCCESS, f"Entry_{i}", 100)

        # First entry should be Entry_10 (0-9 were removed)
        assert log["runs"][0]["message"] == "Entry_10"


class TestSerializeLog:
    """Test log serialization."""

    def test_produces_valid_json(self) -> None:
        """Should produce parseable JSON."""
        log = load_log(None)
        append_run(log, RunStatus.SUCCESS, "test", 1000)
        serialized = serialize_log(log)
        parsed = json.loads(serialized)
        assert parsed["version"] == 1

    def test_returns_bytes(self) -> None:
        """Should return UTF-8 bytes."""
        log = load_log(None)
        result = serialize_log(log)
        assert isinstance(result, bytes)
        result.decode("utf-8")

    def test_pretty_printed(self) -> None:
        """Should use indentation."""
        log = load_log(None)
        append_run(log, RunStatus.SUCCESS, "test", 1000)
        text = serialize_log(log).decode("utf-8")
        assert "\n" in text


class TestRunStatus:
    """Test the RunStatus enum."""

    def test_values(self) -> None:
        """Enum values should match expected strings."""
        assert RunStatus.SUCCESS.value == "success"
        assert RunStatus.DUPLICATE.value == "duplicate"
        assert RunStatus.ERROR.value == "error"

    def test_is_string_enum(self) -> None:
        """Should be usable as a string."""
        # RunStatus inherits from str, so .value gives the string value
        assert RunStatus.SUCCESS == "success"
        assert RunStatus.SUCCESS.value == "success"
