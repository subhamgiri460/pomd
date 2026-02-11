# NSE Pre-Open Data Archiver

Automated daily archival of NSE (National Stock Exchange of India) pre-open market data to a GitHub repository using GitHub Actions.

## What It Does

This pipeline:

1. 🌐 **Fetches** pre-open market data from NSE's API
2. 📦 **Compresses** the response with gzip (deterministic, for reliable dedup)
3. 🔐 **Hashes** the compressed data (SHA-256)
4. 🔍 **Checks** if this exact data was already archived (deduplication)
5. ⬆️ **Uploads** the `.gz` file to the `data/` directory
6. 📋 **Updates** `index.json` with metadata (including raw content URL)
7. 📊 **Logs** the run outcome to `log.json`

## Project Structure

```
├── .github/workflows/
│   └── nse-preopen.yml          # GitHub Actions workflow (daily schedule)
├── src/
│   ├── config.py                # All constants & environment variables
│   ├── nse_client.py            # NSE HTTP client (session, cookies, retries)
│   ├── compression.py           # Gzip + SHA256 + filename builder
│   ├── github_repo.py           # GitHub Contents API client
│   ├── index_manager.py         # index.json CRUD + dedup
│   ├── log_manager.py           # Structured run log
│   └── main.py                  # Pipeline orchestrator
├── tests/                       # Comprehensive test suite
├── data/                        # Archived .gz files
├── index.json                   # Manifest of all archived files
└── log.json                     # Run history
```

## Setup

### 1. Create a GitHub Repository

Create a new repository (or use an existing one) where the data will be archived.

### 2. Create a Personal Access Token (PAT)

1. Go to [GitHub Settings → Developer settings → Personal access tokens → Fine-grained tokens](https://github.com/settings/tokens?type=beta)
2. Create a token with:
   - **Repository access**: Only select your archive repository (if different from the workflow repo)
   - **Permissions**: Contents → Read and write

### 3. Add Repository Secrets

1. Go to your repository → Settings → Secrets and variables → Actions
2. Add new secrets:
   - **Name**: `TARGET_GITHUB_TOKEN`
   - **Value**: Your PAT from step 2
   - **Name**: `TARGET_GITHUB_REPO`
   - **Value**: The target repository in `owner/repo` format (e.g., `my-user/nse-data-archive`)

### 4. Enable GitHub Actions

The workflow is triggered manually from the Actions tab ("Run workflow").

## Configuration

All configuration is centralized in `src/config.py`. Environment variables can override defaults:

| Environment Variable | Default | Description |
|---|---|---|
| `GITHUB_TOKEN` | *(required)* | GitHub PAT with repo scope |
| `GITHUB_REPO` | *(required)* | Target repository (`owner/repo`) |
| `GITHUB_BRANCH` | `main` | Target branch |
| `NSE_URL` | NSE API URL | API endpoint (update if NSE changes it) |
| `USER_AGENT` | Chrome-like UA | Browser User-Agent string |
| `REQUEST_TIMEOUT` | `30` | Seconds per HTTP request |
| `MAX_RETRIES` | `3` | Retry count with exponential backoff |
| `DATA_DIR` | `data` | Archive subdirectory |
| `INDEX_FILE` | `index.json` | Manifest file path |
| `LOG_FILE` | `log.json` | Run log file path |

## Development

### Install Dependencies

```bash
pip install -r requirements-dev.txt
```

### Run Tests

```bash
pytest tests/ -v
```

### Run with Coverage

```bash
pytest tests/ -v --cov=src --cov-report=term-missing
```

### Manual Local Run

```bash
export GITHUB_TOKEN="ghp_your_token"
export GITHUB_REPO="your-username/your-repo"
python -m src.main
```

## Data Format

### index.json

```json
{
  "version": 1,
  "files": [
    {
      "filename": "preopen_20260211T033800Z_abc123def456.json.gz",
      "hash": "abc123def456...",
      "timestamp": "2026-02-11T03:38:00+00:00",
      "size_bytes": 45678,
      "raw_size_bytes": 123456,
      "url": "https://raw.githubusercontent.com/owner/repo/main/data/preopen_20260211T033800Z_abc123def456.json.gz",
      "records_count": 200
    }
  ],
  "total_count": 1,
  "last_updated": "2026-02-11T03:38:05+00:00"
}
```

### log.json

```json
{
  "version": 1,
  "runs": [
    {
      "timestamp": "2026-02-11T03:38:10+00:00",
      "status": "success",
      "message": "Archived preopen_20260211T033800Z_abc123def456.json.gz",
      "duration_ms": 5432,
      "filename": "preopen_20260211T033800Z_abc123def456.json.gz"
    }
  ],
  "total_runs": 1
}
```

## Robustness

- **Session-based NSE requests** — establishes cookies before API call
- **Configurable User-Agent** — easily updated when NSE blocks old UAs
- **Response validation** — checks content-type, body length, JSON structure
- **Deterministic gzip** — `mtime=0` ensures same data → same hash
- **Retry with exponential backoff** — handles transient failures
- **Fail-soft index.json** — missing/corrupt file creates fresh index
- **Log rotation** — capped at 500 entries
- **Comprehensive tests** — every module independently tested

## License

MIT
