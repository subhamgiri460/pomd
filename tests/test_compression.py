"""Tests for src.compression — gzip, SHA256, and filename generation."""

from __future__ import annotations

import gzip
import hashlib
from datetime import datetime, timezone

import pytest

from src.compression import (
    gzip_compress,
    sha256_hex,
    build_filename,
    get_utc_now,
)
from src.config import FILENAME_PREFIX, FILENAME_EXTENSION


class TestGzipCompress:
    """Test deterministic gzip compression."""

    def test_compressed_data_is_valid_gzip(self) -> None:
        """Output should be decompressible by gzip."""
        original = b'{"data": [1, 2, 3]}'
        compressed = gzip_compress(original)
        decompressed = gzip.decompress(compressed)
        assert decompressed == original

    def test_deterministic_output(self) -> None:
        """Same input should always produce same output (mtime=0)."""
        data = b"identical data for determinism test"
        result1 = gzip_compress(data)
        result2 = gzip_compress(data)
        assert result1 == result2

    def test_compression_reduces_size(self) -> None:
        """Compressed output should be smaller than input for typical JSON."""
        # Repetitive data compresses well
        data = (b'{"symbol": "RELIANCE", "price": 1250.00}' * 100)
        compressed = gzip_compress(data)
        assert len(compressed) < len(data)

    def test_empty_input(self) -> None:
        """Empty bytes should produce valid (small) gzip output."""
        compressed = gzip_compress(b"")
        assert gzip.decompress(compressed) == b""

    def test_custom_compression_level(self) -> None:
        """Different compression levels should produce valid output."""
        data = b"test data" * 50
        fast = gzip_compress(data, compresslevel=1)
        best = gzip_compress(data, compresslevel=9)
        # Both should decompress to the same data
        assert gzip.decompress(fast) == data
        assert gzip.decompress(best) == data
        # Best compression should be smaller or equal
        assert len(best) <= len(fast)


class TestSha256Hex:
    """Test SHA-256 hashing."""

    def test_known_hash(self) -> None:
        """Verify against a known SHA-256 value."""
        data = b"hello world"
        expected = hashlib.sha256(data).hexdigest()
        assert sha256_hex(data) == expected

    def test_returns_lowercase_hex(self) -> None:
        """Hash should be lowercase hex, 64 characters."""
        result = sha256_hex(b"test")
        assert len(result) == 64
        assert result == result.lower()
        assert all(c in "0123456789abcdef" for c in result)

    def test_different_inputs_different_hashes(self) -> None:
        """Different data should produce different hashes."""
        hash1 = sha256_hex(b"data_v1")
        hash2 = sha256_hex(b"data_v2")
        assert hash1 != hash2

    def test_empty_input(self) -> None:
        """Empty bytes should produce the well-known empty SHA-256."""
        expected = hashlib.sha256(b"").hexdigest()
        assert sha256_hex(b"") == expected


class TestBuildFilename:
    """Test filename generation."""

    def test_format_with_utc_timestamp(self) -> None:
        """Should produce correct filename format."""
        ts = datetime(2026, 2, 11, 3, 38, 0, tzinfo=timezone.utc)
        hash_hex = "abc123def456789012345678901234567890abcdef1234567890abcdef123456"
        result = build_filename(ts, hash_hex)

        assert result == f"{FILENAME_PREFIX}_20260211T033800Z_abc123def456{FILENAME_EXTENSION}"

    def test_uses_first_12_chars_of_hash(self) -> None:
        """Filename should use only first 12 chars of hash for readability."""
        ts = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        hash_hex = "a" * 64
        result = build_filename(ts, hash_hex)
        assert "aaaaaaaaaaaa" in result  # 12 'a' chars
        assert "aaaaaaaaaaaaa" not in result  # NOT 13

    def test_naive_datetime_treated_as_utc(self) -> None:
        """Naive datetime should be treated as UTC."""
        ts_naive = datetime(2026, 6, 15, 12, 30, 45)
        ts_utc = datetime(2026, 6, 15, 12, 30, 45, tzinfo=timezone.utc)
        hash_hex = "b" * 64

        result_naive = build_filename(ts_naive, hash_hex)
        result_utc = build_filename(ts_utc, hash_hex)
        assert result_naive == result_utc

    def test_filename_has_correct_extension(self) -> None:
        """Filename should end with .json.gz."""
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = build_filename(ts, "c" * 64)
        assert result.endswith(".json.gz")

    def test_filename_starts_with_prefix(self) -> None:
        """Filename should start with the configured prefix."""
        ts = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = build_filename(ts, "d" * 64)
        assert result.startswith(FILENAME_PREFIX)


class TestGetUtcNow:
    """Test UTC time helper."""

    def test_returns_timezone_aware(self) -> None:
        """Should return a timezone-aware datetime."""
        now = get_utc_now()
        assert now.tzinfo is not None

    def test_is_utc(self) -> None:
        """Should be in UTC timezone."""
        now = get_utc_now()
        assert now.tzinfo == timezone.utc
