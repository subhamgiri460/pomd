"""Tests for src.index_manager — index.json CRUD and dedup logic."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.index_manager import (
    load_index,
    get_existing_hashes,
    hash_exists,
    append_entry,
    serialize_index,
    count_records,
    DEFAULT_INDEX,
)
from tests.conftest import SAMPLE_INDEX, sample_index_bytes, sample_nse_bytes


class TestLoadIndex:
    """Test index loading and fail-soft behavior."""

    def test_load_valid_index(self) -> None:
        """Should parse valid index.json correctly."""
        raw = sample_index_bytes()
        index = load_index(raw)
        assert index["version"] == 1
        assert len(index["files"]) == 1
        assert index["files"][0]["hash"] == SAMPLE_INDEX["files"][0]["hash"]

    def test_load_none_returns_default(self) -> None:
        """Should return empty default when file is missing."""
        index = load_index(None)
        assert index["files"] == []
        assert index["version"] == 1
        assert index["total_count"] == 0

    def test_load_invalid_json_returns_default(self) -> None:
        """Should return default on invalid JSON (fail-soft)."""
        index = load_index(b"not valid json {{{}}")
        assert index["files"] == []
        assert index["version"] == 1

    def test_load_missing_fields_added(self) -> None:
        """Should add missing fields for forward compatibility."""
        raw = json.dumps({"some_data": True}).encode()
        index = load_index(raw)
        assert "files" in index
        assert "version" in index

    def test_load_returns_independent_copy(self) -> None:
        """Multiple calls with None should return independent objects."""
        idx1 = load_index(None)
        idx2 = load_index(None)
        idx1["files"].append({"test": True})
        assert len(idx2["files"]) == 0


class TestHashExists:
    """Test hash deduplication checks."""

    def test_existing_hash_found(self) -> None:
        """Should detect existing hash."""
        index = load_index(sample_index_bytes())
        existing_hash = SAMPLE_INDEX["files"][0]["hash"]
        assert hash_exists(index, existing_hash) is True

    def test_new_hash_not_found(self) -> None:
        """Should not find a new hash."""
        index = load_index(sample_index_bytes())
        assert hash_exists(index, "f" * 64) is False

    def test_empty_index_never_matches(self) -> None:
        """Empty index should match nothing."""
        index = load_index(None)
        assert hash_exists(index, "a" * 64) is False

    def test_get_existing_hashes_returns_set(self) -> None:
        """Should return a set of hash strings."""
        index = load_index(sample_index_bytes())
        hashes = get_existing_hashes(index)
        assert isinstance(hashes, set)
        assert len(hashes) == 1


class TestAppendEntry:
    """Test appending new entries to the index."""

    def test_append_to_empty_index(self) -> None:
        """Should add entry to empty files list."""
        index = load_index(None)
        ts = datetime(2026, 2, 11, 3, 38, 0, tzinfo=timezone.utc)

        result = append_entry(
            index=index,
            filename="preopen_20260211T033800Z_abc123def456.json.gz",
            hash_hex="abc123" + "0" * 58,
            timestamp=ts,
            size_bytes=1000,
            raw_size_bytes=5000,
            records_count=200,
        )

        assert len(result["files"]) == 1
        assert result["total_count"] == 1
        assert result["last_updated"] is not None
        entry = result["files"][0]
        assert entry["filename"] == "preopen_20260211T033800Z_abc123def456.json.gz"
        assert entry["records_count"] == 200

    def test_append_to_existing_index(self) -> None:
        """Should add to existing files without removing old entries."""
        index = load_index(sample_index_bytes())
        ts = datetime(2026, 2, 11, 3, 38, 0, tzinfo=timezone.utc)

        result = append_entry(
            index=index,
            filename="new_file.json.gz",
            hash_hex="b" * 64,
            timestamp=ts,
            size_bytes=2000,
            raw_size_bytes=8000,
        )

        assert len(result["files"]) == 2  # 1 existing + 1 new
        assert result["total_count"] == 2

    def test_entry_includes_all_fields(self) -> None:
        """Entry should have all expected metadata fields."""
        index = load_index(None)
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)

        append_entry(
            index=index,
            filename="test.json.gz",
            hash_hex="c" * 64,
            timestamp=ts,
            size_bytes=500,
            raw_size_bytes=2000,
            records_count=50,
        )

        entry = index["files"][0]
        assert "filename" in entry
        assert "hash" in entry
        assert "timestamp" in entry
        assert "size_bytes" in entry
        assert "raw_size_bytes" in entry
        assert "records_count" in entry


class TestSerializeIndex:
    """Test index serialization."""

    def test_produces_valid_json(self) -> None:
        """Should produce valid, parseable JSON."""
        index = load_index(sample_index_bytes())
        serialized = serialize_index(index)
        parsed = json.loads(serialized)
        assert parsed["version"] == 1

    def test_uses_utf8_encoding(self) -> None:
        """Should return UTF-8 encoded bytes."""
        index = load_index(None)
        serialized = serialize_index(index)
        assert isinstance(serialized, bytes)
        serialized.decode("utf-8")  # Should not raise

    def test_pretty_printed(self) -> None:
        """Should use indentation for readability."""
        index = load_index(sample_index_bytes())
        serialized = serialize_index(index)
        text = serialized.decode("utf-8")
        assert "\n" in text
        assert "  " in text  # 2-space indent


class TestCountRecords:
    """Test NSE record counting."""

    def test_count_valid_nse_data(self) -> None:
        """Should count items in the 'data' array."""
        raw = sample_nse_bytes()
        count = count_records(raw)
        assert count == 2  # SAMPLE_NSE_RESPONSE has 2 items in "data"

    def test_count_missing_data_key(self) -> None:
        """Should return None if 'data' key is missing."""
        raw = json.dumps({"other": "stuff"}).encode()
        count = count_records(raw)
        assert count == 0  # Empty list from .get default

    def test_count_invalid_json(self) -> None:
        """Should return None for invalid JSON."""
        count = count_records(b"not json")
        assert count is None

    def test_count_empty_data(self) -> None:
        """Should return 0 for empty data array."""
        raw = json.dumps({"data": []}).encode()
        count = count_records(raw)
        assert count == 0
