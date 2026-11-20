"""Pytest configuration and fixtures for FMHY Tracker tests."""

import pytest
import json
import tempfile
import os
from pathlib import Path


@pytest.fixture(autouse=True)
def isolate_history_dir(tmp_path):
    """Keep history tests from reading or mutating project-local history."""
    from fmhy_tracker.config import config

    original_history_dir = config.history_dir
    config.history_dir = str(tmp_path / "history")
    yield
    config.history_dir = original_history_dir


@pytest.fixture
def sample_commit():
    """Sample commit data for testing."""
    return {
        "sha": "abc123def456789",
        "url": "https://api.github.com/repos/fmhy/edit/commits/abc123def456789",
        "commit": {
            "message": "Add new streaming site",
            "author": {"date": "2024-01-15T10:30:00Z"},
        },
    }


@pytest.fixture
def sample_commits():
    """List of sample commits for testing."""
    return [
        {
            "sha": "abc123def456789",
            "url": "https://api.github.com/repos/fmhy/edit/commits/abc123",
            "commit": {
                "message": "Add new streaming site",
                "author": {"date": "2024-01-15T10:30:00Z"},
            },
        },
        {
            "sha": "def456ghi789012",
            "url": "https://api.github.com/repos/fmhy/edit/commits/def456",
            "commit": {
                "message": "Update video tools",
                "author": {"date": "2024-01-14T09:00:00Z"},
            },
        },
    ]


@pytest.fixture
def sample_added_links():
    """Sample added links for testing."""
    return [
        {
            "link": "* ⭐ **[StreamSite](https://stream.example.com)** - Best streaming",
            "source": "video",
        },
        {
            "link": "* [ToolName](https://tool.example.com) - A useful tool",
            "source": "tools",
        },
        {
            "link": "* ⭐ **[AudioApp](https://audio.example.com)** - Audio player",
            "source": "audio",
        },
    ]


@pytest.fixture
def sample_removed_links():
    """Sample removed links for testing."""
    return [
        {
            "link": "* ⭐ **[OldSite](https://old.example.com)** - Deprecated",
            "source": "video",
        },
        {
            "link": "* [StreamSite](https://stream-old.example.com) - Old URL",
            "source": "video",
        },
    ]


@pytest.fixture
def sample_tracker_data():
    """Sample tracker output data for testing."""
    return {
        "lastUpdated": "2024-01-15T10:30:00Z",
        "totalAdded": 3,
        "totalRemoved": 2,
        "totalNew": 2,
        "totalUpdated": 1,
        "totalCommits": 2,
        "commits": [
            {
                "sha": "abc123def456789",
                "date": "2024-01-15T10:30:00Z",
                "message": "Add new streaming site",
                "added": [
                    {
                        "link": "* ⭐ **[StreamSite](https://stream.example.com)**",
                        "source": "video",
                        "type": "new",
                    }
                ],
                "removed": [],
            },
            {
                "sha": "def456ghi789012",
                "date": "2024-01-14T09:00:00Z",
                "message": "Update tools",
                "added": [
                    {
                        "link": "* [ToolName](https://tool.example.com)",
                        "source": "tools",
                        "type": "updated",
                    }
                ],
                "removed": [
                    {
                        "link": "* [ToolName](https://old-tool.example.com)",
                        "source": "tools",
                        "type": "removed",
                    }
                ],
            },
        ],
    }


@pytest.fixture
def temp_directory():
    """Create a temporary directory for test files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_github_response():
    """Mock GitHub API response for commit details."""
    return {
        "sha": "abc123def456789",
        "files": [
            {
                "filename": "docs/video.md",
                "patch": "+* ⭐ **[NewSite](https://new.example.com)** - New site\n-* [OldSite](https://old.example.com) - Removed",
            }
        ],
    }


@pytest.fixture
def tracker_config(temp_directory):
    """Configuration for tracker testing."""
    return {
        "repo": "fmhy/edit",
        "folder_path": "docs/",
        "last_commit_sha_file": str(temp_directory / "last_commit_sha.txt"),
        "output_file": str(temp_directory / "fmhy_data.json"),
    }
