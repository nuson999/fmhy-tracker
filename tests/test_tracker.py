"""Tests for FMHY Tracker core functionality."""

import pytest
import json
import os
from unittest.mock import Mock, patch, MagicMock

from fmhy_tracker import CommitProcessingError, FMHYTracker


class TestExtractLinkIdentifier:
    """Tests for extract_link_identifier method."""

    def test_extract_simple_link_title(self):
        """Test extracting title from simple markdown link."""
        tracker = FMHYTracker()
        link = "* [StreamSite](https://stream.example.com)"
        result = tracker.extract_link_identifier(link)
        assert result == "streamsite"

    def test_extract_starred_link_title(self):
        """Test extracting title from starred link."""
        tracker = FMHYTracker()
        link = "* ⭐ **[StreamSite](https://stream.example.com)** - Description"
        result = tracker.extract_link_identifier(link)
        assert result == "streamsite"

    def test_extract_bold_link_title(self):
        """Test extracting title from bold formatted link."""
        tracker = FMHYTracker()
        link = "* **[BoldTitle](https://example.com)**"
        result = tracker.extract_link_identifier(link)
        assert result == "boldtitle"

    def test_extract_with_leading_asterisks(self):
        """Test handling of leading asterisks."""
        tracker = FMHYTracker()
        link = "*** [Title](https://example.com)"
        result = tracker.extract_link_identifier(link)
        assert result == "title"

    def test_fallback_to_clean_text(self):
        """Test fallback when no markdown link found."""
        tracker = FMHYTracker()
        link = "* ⭐ Some plain text"
        result = tracker.extract_link_identifier(link)
        assert "plain text" in result.lower()


class TestCategorizeLinks:
    """Tests for categorize_links method."""

    def test_categorize_new_links(self, sample_added_links):
        """Test that truly new links are categorized correctly."""
        tracker = FMHYTracker()
        added, removed = tracker.categorize_links(sample_added_links, [])

        assert len(added) == 3
        assert all(item["type"] == "new" for item in added)
        assert len(removed) == 0

    def test_categorize_removed_links(self, sample_removed_links):
        """Test that removed links are categorized correctly."""
        tracker = FMHYTracker()
        added, removed = tracker.categorize_links([], sample_removed_links)

        assert len(added) == 0
        assert len(removed) == 2
        assert all(item["type"] == "removed" for item in removed)

    def test_categorize_updated_links(self):
        """Test that updated links (same title, different URL) are detected."""
        tracker = FMHYTracker()

        added = [{"link": "* [SameSite](https://new-url.com)", "source": "video"}]
        removed = [{"link": "* [SameSite](https://old-url.com)", "source": "video"}]

        cat_added, cat_removed = tracker.categorize_links(added, removed)

        assert len(cat_added) == 1
        assert cat_added[0]["type"] == "updated"
        assert "relatedLink" in cat_added[0]
        assert len(cat_removed) == 0  # Removed link becomes an update, not a removal


class TestCommitSHAManagement:
    """Tests for commit SHA file management."""

    def test_get_last_commit_sha_no_file(self, tracker_config):
        """Test getting SHA when file doesn't exist."""
        tracker = FMHYTracker(**tracker_config)
        result = tracker.get_last_commit_sha()
        assert result is None

    def test_set_and_get_commit_sha(self, tracker_config):
        """Test setting and retrieving commit SHA."""
        tracker = FMHYTracker(**tracker_config)
        test_sha = "abc123def456"

        tracker.set_last_commit_sha(test_sha)
        result = tracker.get_last_commit_sha()

        assert result == test_sha

    def test_get_last_commit_sha_strips_whitespace(self, tracker_config):
        """Test that SHA is stripped of whitespace."""
        tracker = FMHYTracker(**tracker_config)

        # Write SHA with whitespace
        with open(tracker_config["last_commit_sha_file"], "w") as f:
            f.write("  abc123def456  \n")

        result = tracker.get_last_commit_sha()
        assert result == "abc123def456"


class TestProcessCommit:
    """Tests for process_commit method."""

    @patch("fmhy_tracker.tracker.requests.get")
    def test_process_commit_extracts_added_links(self, mock_get, sample_commit):
        """Test that added links are extracted from commit."""
        tracker = FMHYTracker()

        mock_response = Mock()
        mock_response.json.return_value = {
            "sha": sample_commit["sha"],
            "files": [
                {
                    "filename": "docs/video.md",
                    "patch": "+* ⭐ **[NewSite](https://new.example.com)** - New streaming site",
                }
            ],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        added, removed = tracker.process_commit(sample_commit)

        assert len(added) == 1
        assert "NewSite" in added[0]["link"]
        assert added[0]["source"] == "video"

    @patch("fmhy_tracker.tracker.requests.get")
    def test_process_commit_extracts_removed_links(self, mock_get, sample_commit):
        """Test that removed links are extracted from commit."""
        tracker = FMHYTracker()

        mock_response = Mock()
        mock_response.json.return_value = {
            "sha": sample_commit["sha"],
            "files": [
                {
                    "filename": "docs/video.md",
                    "patch": "-* [OldSite](https://old.example.com) - Removed site",
                }
            ],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        added, removed = tracker.process_commit(sample_commit)

        assert len(removed) == 1
        assert "OldSite" in removed[0]["link"]

    @patch("fmhy_tracker.tracker.requests.get")
    def test_process_commit_handles_non_markdown_files(self, mock_get, sample_commit):
        """Test that non-markdown files are ignored."""
        tracker = FMHYTracker()

        mock_response = Mock()
        mock_response.json.return_value = {
            "sha": sample_commit["sha"],
            "files": [{"filename": "docs/config.json", "patch": "+some config"}],
        }
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        added, removed = tracker.process_commit(sample_commit)

        assert len(added) == 0
        assert len(removed) == 0

    @patch("fmhy_tracker.tracker.requests.get")
    def test_process_commit_handles_request_error(self, mock_get, sample_commit):
        """Test graceful handling of request errors."""
        tracker = FMHYTracker()

        mock_get.side_effect = Exception("Network error")

        added, removed = tracker.process_commit(sample_commit)

        assert added == []
        assert removed == []

    @patch("fmhy_tracker.tracker.requests.get")
    def test_process_commit_can_raise_on_error(self, mock_get, sample_commit):
        """Test strict processing raises so callers can avoid advancing state."""
        tracker = FMHYTracker()

        mock_get.side_effect = Exception("Network error")

        with pytest.raises(CommitProcessingError):
            tracker.process_commit(sample_commit, raise_on_error=True)

    def test_run_does_not_advance_sha_when_processing_fails(
        self, tracker_config, sample_commit
    ):
        """Test failed new commits are retried instead of being marked processed."""
        tracker = FMHYTracker(**tracker_config)

        with (
            patch.object(tracker, "get_new_commits", return_value=[sample_commit]),
            patch.object(
                tracker,
                "process_commit",
                side_effect=CommitProcessingError("boom"),
            ),
            patch.object(tracker, "save_data") as mock_save_data,
        ):
            tracker.run()

        assert tracker.get_last_commit_sha() is None
        mock_save_data.assert_not_called()


class TestGetNewCommits:
    """Tests for get_new_commits method."""

    @patch("fmhy_tracker.tracker.requests.get")
    def test_get_new_commits_returns_all_when_no_sha(self, mock_get):
        """Test that first commit is returned when no previous SHA."""
        tracker = FMHYTracker()

        mock_response = Mock()
        mock_response.json.return_value = [
            {"sha": "commit1"},
            {"sha": "commit2"},
            {"sha": "commit3"},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        commits = list(tracker.get_new_commits(None))

        assert len(commits) == 1
        assert commits[0]["sha"] == "commit1"

    @patch("fmhy_tracker.tracker.requests.get")
    def test_get_new_commits_returns_new_only(self, mock_get):
        """Test that only new commits are returned."""
        tracker = FMHYTracker()

        mock_response = Mock()
        mock_response.json.return_value = [
            {"sha": "commit1"},
            {"sha": "commit2"},
            {"sha": "commit3"},
        ]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        commits = list(tracker.get_new_commits("commit2"))

        assert len(commits) == 1
        assert commits[0]["sha"] == "commit1"

    @patch("fmhy_tracker.tracker.requests.get")
    def test_get_new_commits_returns_empty_when_up_to_date(self, mock_get):
        """Test that empty list is returned when up to date."""
        tracker = FMHYTracker()

        mock_response = Mock()
        mock_response.json.return_value = [{"sha": "commit1"}, {"sha": "commit2"}]
        mock_response.raise_for_status = Mock()
        mock_get.return_value = mock_response

        commits = list(tracker.get_new_commits("commit1"))

        assert len(commits) == 0

    @patch("fmhy_tracker.tracker.requests.get")
    def test_get_new_commits_follows_pagination_until_last_sha(self, mock_get):
        """Test that pagination is followed until the stored SHA is found."""
        tracker = FMHYTracker()

        first_response = Mock()
        first_response.json.return_value = [
            {"sha": "commit1"},
            {"sha": "commit2"},
        ]
        first_response.links = {"next": {"url": "https://api.github.com/page/2"}}
        first_response.raise_for_status = Mock()

        second_response = Mock()
        second_response.json.return_value = [
            {"sha": "commit3"},
            {"sha": "commit4"},
        ]
        second_response.links = {}
        second_response.raise_for_status = Mock()

        mock_get.side_effect = [first_response, second_response]

        commits = list(tracker.get_new_commits("commit4"))

        assert [commit["sha"] for commit in commits] == [
            "commit3",
            "commit2",
            "commit1",
        ]
        assert mock_get.call_count == 2


class TestSaveData:
    """Tests for save_data method."""

    def test_save_data_creates_json_file(self, tracker_config, sample_tracker_data):
        """Test that data is saved to JSON file."""
        tracker = FMHYTracker(**tracker_config)

        tracker.save_data(sample_tracker_data)

        assert os.path.exists(tracker_config["output_file"])

        with open(tracker_config["output_file"], "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        assert saved_data["totalAdded"] == sample_tracker_data["totalAdded"]
        assert saved_data["totalRemoved"] == sample_tracker_data["totalRemoved"]


class TestExtractLinkTitle:
    """Tests for _extract_link_title method."""

    def test_extract_title_from_markdown_link(self):
        """Test extracting title from markdown link."""
        tracker = FMHYTracker()
        result = tracker._extract_link_title("[Title](https://example.com)")
        assert result == "Title"

    def test_extract_title_returns_original_if_no_match(self):
        """Test that original text is returned if no link found."""
        tracker = FMHYTracker()
        result = tracker._extract_link_title("Plain text without link")
        assert result == "Plain text without link"


class TestHistory:
    """Tests for history functionality."""

    def test_get_history_empty_when_no_files(self, tracker_config):
        """Test that empty list is returned when no history files."""
        tracker = FMHYTracker(**tracker_config)
        history = tracker.get_history()
        assert history == []

    def test_save_and_get_history(self, tracker_config, sample_tracker_data):
        """Test saving and retrieving history."""
        # Set up history path
        import tempfile
        from pathlib import Path
        from fmhy_tracker.config import config

        with tempfile.TemporaryDirectory() as tmpdir:
            config.history_dir = str(Path(tmpdir) / "history")
            tracker = FMHYTracker(**tracker_config)

            tracker.save_history(sample_tracker_data)
            history = tracker.get_history()

            assert len(history) == 1
            assert history[0]["totalAdded"] == sample_tracker_data["totalAdded"]
