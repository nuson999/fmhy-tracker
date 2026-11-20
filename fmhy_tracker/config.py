"""Configuration management for FMHY Tracker."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class Config:
    """Configuration settings for FMHY Tracker."""

    # Default values
    DEFAULT_REPO = "fmhy/edit"
    DEFAULT_FOLDER_PATH = "docs/"
    DEFAULT_OUTPUT_FILE = "fmhy_data.json"
    DEFAULT_LAST_COMMIT_SHA_FILE = "last_commit_sha.txt"
    DEFAULT_HISTORY_DIR = "data/history"
    DEFAULT_GITHUB_TIMEOUT_SECONDS = 30
    DEFAULT_GITHUB_RETRIES = 3

    # Minimum commits to display
    DEFAULT_MIN_COMMITS = 5

    # History settings
    DEFAULT_MAX_HISTORY_FILES = 100
    DEFAULT_MONTHLY_OUTPUT_FILE = "monthly_commits.json"

    # RSS feed defaults
    DEFAULT_RSS_FILE = "feed.xml"
    DEFAULT_RSS_TITLE = "FMHY Tracker - Changes Feed"
    DEFAULT_RSS_LINK = "https://nuson999.github.io/fmhy-tracker"
    DEFAULT_RSS_DESCRIPTION = (
        "Track changes in the FMHY repository - new, updated, and removed links"
    )

    def __init__(self):
        """Initialize configuration from environment variables."""
        self.repo = os.getenv("FMHY_REPO", self.DEFAULT_REPO)
        self.folder_path = os.getenv("FMHY_FOLDER_PATH", self.DEFAULT_FOLDER_PATH)
        self.output_file = os.getenv("FMHY_OUTPUT_FILE", self.DEFAULT_OUTPUT_FILE)
        self.last_commit_sha_file = os.getenv(
            "FMHY_LAST_COMMIT_SHA_FILE", self.DEFAULT_LAST_COMMIT_SHA_FILE
        )
        self.history_dir = os.getenv("FMHY_HISTORY_DIR", self.DEFAULT_HISTORY_DIR)
        self.github_token = os.getenv("GITHUB_TOKEN")
        self.github_timeout_seconds = self._get_int_env(
            "FMHY_GITHUB_TIMEOUT_SECONDS",
            self.DEFAULT_GITHUB_TIMEOUT_SECONDS,
        )
        self.github_retries = self._get_int_env(
            "FMHY_GITHUB_RETRIES",
            self.DEFAULT_GITHUB_RETRIES,
        )

        # Minimum commits to display
        self.min_commits = self._get_int_env(
            "FMHY_MIN_COMMITS",
            self.DEFAULT_MIN_COMMITS,
        )

        # History settings
        self.max_history_files = self._get_int_env(
            "FMHY_MAX_HISTORY",
            self.DEFAULT_MAX_HISTORY_FILES,
        )
        self.monthly_output_file = os.getenv(
            "FMHY_MONTHLY_OUTPUT", self.DEFAULT_MONTHLY_OUTPUT_FILE
        )

        # RSS feed configuration
        self.rss_file = os.getenv("FMHY_RSS_FILE", self.DEFAULT_RSS_FILE)
        self.rss_title = os.getenv("FMHY_RSS_TITLE", self.DEFAULT_RSS_TITLE)
        self.rss_link = os.getenv("FMHY_RSS_LINK", self.DEFAULT_RSS_LINK)
        self.rss_description = os.getenv(
            "FMHY_RSS_DESCRIPTION", self.DEFAULT_RSS_DESCRIPTION
        )

    @property
    def base_path(self) -> Path:
        """Get the base path for the project."""
        return Path(__file__).parent.parent

    @property
    def history_path(self) -> Path:
        """Get the path for history files."""
        return self.base_path / self.history_dir

    def _get_int_env(self, name: str, default: int) -> int:
        """Read an integer environment variable with a safe fallback."""
        raw_value = os.getenv(name)
        if raw_value is None:
            return default
        try:
            return int(raw_value)
        except ValueError:
            logger.warning("Invalid %s=%r; using default %s.", name, raw_value, default)
            return default

    def ensure_history_dir(self) -> None:
        """Ensure the history directory exists."""
        self.history_path.mkdir(parents=True, exist_ok=True)


# Global config instance
config = Config()
