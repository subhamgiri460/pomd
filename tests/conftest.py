"""
Shared test fixtures for the NSE Pre-Open Data Archiver test suite.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from src.config import AppConfig


# ─── Sample Data ─────────────────────────────────────────────────────────────

SAMPLE_NSE_RESPONSE = {
    "data": [
        {
            "metadata": {
                "symbol": "RELIANCE",
                "purpose": "-",
                "yearHigh": 3217.60,
                "yearLow": 1119.50,
            },
            "detail": {
                "preOpenMarket": {
                    "preopen": [
                        {"price": 1250.00, "buyQty": 100, "sellQty": 0},
                        {"price": 1260.00, "buyQty": 0, "sellQty": 50},
                    ],
                    "ato": {"buy": 1000, "sell": 500},
                    "IEP": 1255.50,
                    "totalTradedVolume": 1500,
                    "finalPrice": 1255.50,
                    "finalQuantity": 1500,
                    "lastUpdateTime": "11-Feb-2026 09:08:00",
                    "totalBuyQuantity": 1100,
                    "totalSellQuantity": 550,
                }
            },
        },
        {
            "metadata": {
                "symbol": "TCS",
                "purpose": "-",
                "yearHigh": 4592.25,
                "yearLow": 3056.05,
            },
            "detail": {
                "preOpenMarket": {
                    "preopen": [
                        {"price": 3800.00, "buyQty": 200, "sellQty": 0},
                    ],
                    "ato": {"buy": 500, "sell": 200},
                    "IEP": 3810.00,
                    "totalTradedVolume": 700,
                    "finalPrice": 3810.00,
                    "finalQuantity": 700,
                    "lastUpdateTime": "11-Feb-2026 09:08:00",
                    "totalBuyQuantity": 700,
                    "totalSellQuantity": 200,
                }
            },
        },
    ]
}


def sample_nse_bytes() -> bytes:
    """Return sample NSE response as bytes."""
    return json.dumps(SAMPLE_NSE_RESPONSE).encode("utf-8")


SAMPLE_INDEX = {
    "version": 1,
    "files": [
        {
            "filename": "preopen_20260210T033800Z_aabbccddee11.json.gz",
            "hash": "aabbccddee1122334455667788990011aabbccddee1122334455667788990011",
            "timestamp": "2026-02-10T03:38:00+00:00",
            "size_bytes": 1234,
            "raw_size_bytes": 5678,
            "records_count": 50,
        }
    ],
    "total_count": 1,
    "last_updated": "2026-02-10T03:38:05+00:00",
}


def sample_index_bytes() -> bytes:
    """Return sample index.json as bytes."""
    return json.dumps(SAMPLE_INDEX).encode("utf-8")


FIXED_TIMESTAMP = datetime(2026, 2, 11, 3, 38, 0, tzinfo=timezone.utc)
FIXED_HASH = "abc123def456789012345678901234567890abcdef1234567890abcdef123456"


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def app_config() -> AppConfig:
    """Create a test AppConfig without requiring real env vars."""
    return AppConfig(
        github_token="ghp_test_token_1234567890",
        github_repo="testowner/testrepo",
        github_branch="main",
    )


@pytest.fixture
def nse_response_bytes() -> bytes:
    """Raw NSE response bytes."""
    return sample_nse_bytes()


@pytest.fixture
def index_bytes() -> bytes:
    """Raw index.json bytes."""
    return sample_index_bytes()


@pytest.fixture
def fixed_time() -> datetime:
    """Fixed UTC timestamp for deterministic tests."""
    return FIXED_TIMESTAMP
