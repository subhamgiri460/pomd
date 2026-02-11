"""
Compression and cryptographic hashing utilities.

Uses deterministic gzip (mtime=0) so that identical data always produces
the same compressed output → same SHA256 hash → reliable deduplication.
"""

from __future__ import annotations

import gzip
import hashlib
from datetime import datetime, timezone

from src.config import FILENAME_PREFIX, FILENAME_EXTENSION, TIMESTAMP_FORMAT


def gzip_compress(data: bytes, *, compresslevel: int = 9) -> bytes:
    """
    Compress data with gzip using deterministic settings.

    Args:
        data: Raw bytes to compress.
        compresslevel: Compression level (1-9, default 9 for max compression).

    Returns:
        Gzipped bytes with mtime=0 for determinism.
    """
    return gzip.compress(data, compresslevel=compresslevel, mtime=0)


def sha256_hex(data: bytes) -> str:
    """
    Compute the SHA-256 hash of data and return as lowercase hex string.

    Args:
        data: Bytes to hash.

    Returns:
        64-character lowercase hex digest.
    """
    return hashlib.sha256(data).hexdigest()


def build_filename(timestamp: datetime, hash_hex: str) -> str:
    """
    Build the archive filename from a timestamp and hash.

    Format: preopen_YYYYMMDDTHHMMSSZ_<first-12-chars-of-hash>.json.gz

    Args:
        timestamp: UTC datetime for the filename.
        hash_hex: Full SHA-256 hex string (only first 12 chars used).

    Returns:
        Filename string like "preopen_20260211T033800Z_abc123def456.json.gz".
    """
    # Ensure timestamp is in UTC
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)

    ts_str = timestamp.strftime(TIMESTAMP_FORMAT)
    # Use first 12 chars of hash for readability; full hash is in index.json
    short_hash = hash_hex[:12]
    return f"{FILENAME_PREFIX}_{ts_str}_{short_hash}{FILENAME_EXTENSION}"


def get_utc_now() -> datetime:
    """Return the current UTC time (timezone-aware). Extracted for testability."""
    return datetime.now(timezone.utc)
