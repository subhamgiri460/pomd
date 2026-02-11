"""Tests for src.config — configuration loading and validation."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.config import (
    AppConfig,
    ConfigError,
    NSE_API_URL,
    DEFAULT_BRANCH,
    DEFAULT_MAX_RETRIES,
    DEFAULT_REQUEST_TIMEOUT,
    DEFAULT_RETRY_DELAY,
    DEFAULT_USER_AGENT,
    GITHUB_API_BASE,
)


class TestAppConfigFromEnv:
    """Test AppConfig.from_env() with various env var combinations."""

    def test_from_env_with_required_vars(self) -> None:
        """Should load successfully with minimum required env vars."""
        env = {
            "GITHUB_TOKEN": "ghp_abc123",
            "GITHUB_REPO": "owner/repo",
        }
        with patch.dict(os.environ, env, clear=False):
            config = AppConfig.from_env()

        assert config.github_token == "ghp_abc123"
        assert config.github_repo == "owner/repo"
        assert config.github_branch == DEFAULT_BRANCH
        assert config.nse_url == NSE_API_URL
        assert config.max_retries == DEFAULT_MAX_RETRIES
        assert config.request_timeout == DEFAULT_REQUEST_TIMEOUT

    def test_from_env_with_target_vars(self) -> None:
        """Should prioritize TARGET_* env vars."""
        env = {
            "GITHUB_TOKEN": "ghp_backup",
            "GITHUB_REPO": "backup/repo",
            "TARGET_GITHUB_TOKEN": "ghp_primary",
            "TARGET_GITHUB_REPO": "primary/repo",
        }
        with patch.dict(os.environ, env, clear=False):
            config = AppConfig.from_env()

        assert config.github_token == "ghp_primary"
        assert config.github_repo == "primary/repo"

    def test_from_env_strips_whitespace(self) -> None:
        """Should strip whitespace from token and repo."""
        env = {
            "GITHUB_TOKEN": " ghp_abc123 \n",
            "GITHUB_REPO": " owner/repo \n",
        }
        with patch.dict(os.environ, env, clear=False):
            config = AppConfig.from_env()

        assert config.github_token == "ghp_abc123"
        assert config.github_repo == "owner/repo"

    def test_from_env_all_optional_vars(self) -> None:
        """Should pick up all optional env vars."""
        env = {
            "GITHUB_TOKEN": "ghp_xyz",
            "GITHUB_REPO": "org/data-repo",
            "GITHUB_BRANCH": "develop",
            "NSE_URL": "https://custom.nse.url/api",
            "USER_AGENT": "CustomBot/2.0",
            "REQUEST_TIMEOUT": "60",
            "MAX_RETRIES": "5",
            "RETRY_DELAY": "5",
            "DATA_DIR": "archive",
            "INDEX_FILE": "manifest.json",
            "LOG_FILE": "runs.json",
            "COMMIT_AUTHOR_NAME": "Custom Bot",
            "COMMIT_AUTHOR_EMAIL": "custom@bot.dev",
        }
        with patch.dict(os.environ, env, clear=False):
            config = AppConfig.from_env()

        assert config.github_branch == "develop"
        assert config.nse_url == "https://custom.nse.url/api"
        assert config.user_agent == "CustomBot/2.0"
        assert config.request_timeout == 60
        assert config.max_retries == 5
        assert config.retry_delay == 5
        assert config.data_dir == "archive"
        assert config.index_file == "manifest.json"
        assert config.log_file == "runs.json"
        assert config.commit_author_name == "Custom Bot"
        assert config.commit_author_email == "custom@bot.dev"

    def test_from_env_missing_token_raises(self) -> None:
        """Should raise ConfigError when GITHUB_TOKEN is missing."""
        env = {"GITHUB_REPO": "owner/repo"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
                AppConfig.from_env()

    def test_from_env_missing_repo_raises(self) -> None:
        """Should raise ConfigError when GITHUB_REPO is missing."""
        env = {"GITHUB_TOKEN": "ghp_abc"}
        with patch.dict(os.environ, env, clear=True):
            with pytest.raises(ConfigError, match="GITHUB_REPO"):
                AppConfig.from_env()


class TestAppConfigValidation:
    """Test AppConfig validation rules."""

    def test_empty_token_raises(self) -> None:
        """Empty token string should be rejected."""
        with pytest.raises(ConfigError, match="GITHUB_TOKEN is required"):
            AppConfig(github_token="", github_repo="owner/repo")

    def test_invalid_repo_format_raises(self) -> None:
        """Repo without slash should be rejected."""
        with pytest.raises(ConfigError, match="owner/repo"):
            AppConfig(github_token="ghp_abc", github_repo="just-a-name")

    def test_valid_config_computes_api_url(self, app_config: AppConfig) -> None:
        """Should compute GitHub API URL from repo."""
        expected = f"{GITHUB_API_BASE}/repos/testowner/testrepo/contents"
        assert app_config.github_api_url == expected

    def test_valid_config_builds_nse_headers(self, app_config: AppConfig) -> None:
        """Should build NSE headers dict with required keys."""
        headers = app_config.nse_headers
        assert "User-Agent" in headers
        assert "Accept" in headers
        assert "Referer" in headers
        assert "Connection" in headers

    def test_config_is_immutable(self, app_config: AppConfig) -> None:
        """Frozen dataclass should reject attribute assignment."""
        with pytest.raises(AttributeError):
            app_config.github_token = "new_token"  # type: ignore[misc]
