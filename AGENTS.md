# NSE Pre-Open Data Archiver Agent Instructions

This document provides context and instructions for AI agents or developers maintaining this repository. The goal is to ensure the codebase remains robust, maintainable, and easy to update if the NSE API changes.

## Project Overview

This project archives daily pre-open market data from the National Stock Exchange of India (NSE). It runs daily via GitHub Actions, fetches data, compresses it, hashes it for deduplication, and stores it in the `data/` directory. An `index.json` file tracks all archived files.

### Key Components

*   **`src/nse_client.py`**: Fetches data from NSE. Crucial: Uses `curl` via `subprocess` to bypass NSE's WAF (Web Application Firewall) which often blocks standard Python HTTP libraries (even with headers).
*   **`src/github_repo.py`**: Handles GitHub API interactions (reading/writing files). Uses retry logic for robustness.
*   **`src/compression.py`**: Handles deterministic gzip compression (mtime=0) and SHA-256 hashing.
*   **`src/index_manager.py`**: Manages the `index.json` manifest.
*   **`src/main.py`**: Orchestrates the pipeline.

## NSE API Details

*   **Endpoint**: `https://www.nseindia.com/api/market-data-pre-open?key=ALL&selectValFormat=crores`
*   **Method**: GET
*   **Headers Required**:
    *   `User-Agent`: Must mimic a real browser (e.g., Chrome on Windows).
    *   `Referer`: `https://www.nseindia.com/` (Essential).
    *   `Accept`: `application/json`
    *   `Connection`: `keep-alive`
*   **Response Format** (as of Feb 2026):
    *   JSON Object (Dict)
    *   Key `data`: A list of objects.
    *   Each object in `data` has `metadata` (symbol info) and `detail` (price/quantity info).
    *   Other keys: `timestamp`, `advances`, `declines`, `unchanged`, `totalTradedValue`.

### Example Response Structure

```json
{
  "declines": 12,
  "unchanged": 5,
  "advances": 40,
  "timestamp": "11-Feb-2026 09:07:45",
  "data": [
    {
      "metadata": {
        "symbol": "RELIANCE",
        "identifier": "RELIANCEEQN",
        ...
      },
      "detail": {
        "preOpenMarket": {
          "preopen": [...],
          "ato": {...},
          "finalPrice": 2450.00,
          ...
        }
      }
    },
    ...
  ]
}
```

## Maintenance Instructions

### 1. If NSE Changes the API URL
*   Update `NSE_API_PATH` or `NSE_API_QUERY` in `src/config.py`.
*   Verify with `curl` that the new URL works with the existing headers.

### 2. If NSE Blocks the Request (403 Forbidden / 503 Service Unavailable)
*   **Check User-Agent**: Update `DEFAULT_USER_AGENT` in `src/config.py` to a newer browser string.
*   **Check Headers**: NSE might require new headers (e.g., specific `Accept-Language` or `sec-ch-ua`). Use a browser's Developer Tools (Network tab) to inspect a working request from `nseindia.com` and replicate the headers in `src/config.py`.
*   **Curl Flags**: Ensure `curl` flags in `src/nse_client.py` match the working browser request (e.g., `--http1.1` is critical).

### 3. If NSE Changes Response Format
*   **Validation**: Update `_validate_response` in `src/nse_client.py` to match the new structure.
*   **Pipeline**: If the data is no longer JSON, update `src/compression.py` and `src/main.py` to handle the new format (e.g., CSV).

### 4. Debugging
*   **Run Locally**: Use `python -m src.main` with environment variables set (`GITHUB_TOKEN`, `GITHUB_REPO`).
*   **Check Logs**: The `log.json` file in the repo contains the history of runs.
*   **Test with Curl**: Use `curl -v` to debug network issues directly.

## Development Guidelines

*   **Isolation**: Keep `NSEClient` logic separate from `GitHubRepoClient` logic.
*   **Testing**: Write unit tests for new logic. Mock external calls (NSE, GitHub).
*   **Robustness**: Always assume the network is flaky and the API can change. Use retries and validation.
*   **No Hardcoding**: Put all constants in `src/config.py`.

## Future Improvements

*   **Alerting**: Integrate with Slack/Discord webhooks for real-time failure alerts.
*   **Dashboard**: A simple HTML page hosted on GitHub Pages to visualize `log.json`.
*   **Proxy Support**: If NSE blocks GitHub Actions IPs, add proxy support to `NSEClient`.
