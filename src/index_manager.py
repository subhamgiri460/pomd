"""
Index manager — CRUD operations for the index.json manifest file.

The index.json tracks all archived files with metadata for
deduplication and retrieval.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


# ─── Schema ──────────────────────────────────────────────────────────────────

DEFAULT_INDEX: dict[str, Any] = {
    "version": 1,
    "files": [],
    "total_count": 0,
    "last_updated": None,
}


def _make_entry(
    filename: str,
    hash_hex: str,
    timestamp: datetime,
    size_bytes: int,
    raw_size_bytes: int,
    records_count: int | None = None,
) -> dict[str, Any]:
    """Build a single index entry."""
    return {
        "filename": filename,
        "hash": hash_hex,
        "timestamp": timestamp.isoformat(),
        "size_bytes": size_bytes,            # compressed size
        "raw_size_bytes": raw_size_bytes,    # original JSON size
        "records_count": records_count,       # number of pre-open records
    }


# ─── Core Functions ──────────────────────────────────────────────────────────

def load_index(raw: bytes | None) -> dict[str, Any]:
    """
    Parse raw index.json bytes into a dict.

    If raw is None (file doesn't exist yet), returns the default
    empty index structure. This implements the "fail-soft" behavior.

    Args:
        raw: Raw bytes of index.json, or None if file is missing.

    Returns:
        Parsed index dict with "files" list.
    """
    if raw is None:
        logger.info("No existing index.json — initializing empty index")
        return json.loads(json.dumps(DEFAULT_INDEX))  # deep copy

    try:
        index = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        logger.warning(
            "Failed to parse index.json (%s). "
            "Starting with empty index to avoid data loss.",
            exc,
        )
        return json.loads(json.dumps(DEFAULT_INDEX))

    # Ensure required fields exist (forward compatibility)
    if "files" not in index:
        index["files"] = []
    if "version" not in index:
        index["version"] = 1
    if "total_count" not in index:
        index["total_count"] = len(index["files"])

    return index


def get_existing_hashes(index: dict[str, Any]) -> set[str]:
    """
    Extract all hashes from the index for O(1) dedup lookups.

    Returns:
        Set of hash strings.
    """
    return {entry["hash"] for entry in index.get("files", []) if "hash" in entry}


def hash_exists(index: dict[str, Any], hash_hex: str) -> bool:
    """
    Check if a hash already exists in the index.

    Args:
        index: Parsed index dict.
        hash_hex: SHA-256 hex string to check.

    Returns:
        True if the hash is already archived.
    """
    existing = get_existing_hashes(index)
    return hash_hex in existing


def append_entry(
    index: dict[str, Any],
    filename: str,
    hash_hex: str,
    timestamp: datetime,
    size_bytes: int,
    raw_size_bytes: int,
    records_count: int | None = None,
) -> dict[str, Any]:
    """
    Add a new file entry to the index.

    Args:
        index: Parsed index dict (modified in place AND returned).
        filename: Archive filename.
        hash_hex: SHA-256 of the gzipped data.
        timestamp: UTC timestamp of the fetch.
        size_bytes: Compressed file size.
        raw_size_bytes: Original JSON size.
        records_count: Number of pre-open data records (optional).

    Returns:
        Updated index dict.
    """
    entry = _make_entry(
        filename=filename,
        hash_hex=hash_hex,
        timestamp=timestamp,
        size_bytes=size_bytes,
        raw_size_bytes=raw_size_bytes,
        records_count=records_count,
    )
    index["files"].append(entry)
    index["total_count"] = len(index["files"])
    index["last_updated"] = datetime.now(timezone.utc).isoformat()

    logger.info(
        "Added entry to index: %s (hash=%s…, %d bytes)",
        filename,
        hash_hex[:12],
        size_bytes,
    )
    return index


def serialize_index(index: dict[str, Any]) -> bytes:
    """
    Serialize the index to pretty-printed JSON bytes.

    Returns:
        UTF-8 encoded JSON bytes with 2-space indentation.
    """
    return json.dumps(
        index, indent=2, ensure_ascii=False, sort_keys=False
    ).encode("utf-8")


def count_records(raw_data: bytes) -> int | None:
    """
    Try to count the number of pre-open records in the raw NSE data.

    NSE returns {"data": [...]}, so we count the items in the "data" array.

    Returns:
        Number of records, or None if structure is unexpected.
    """
    try:
        parsed = json.loads(raw_data)
        data = parsed.get("data", [])
        if isinstance(data, list):
            return len(data)
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        pass
    return None
