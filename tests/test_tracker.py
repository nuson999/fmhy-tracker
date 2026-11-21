"""Tests for FMHY Tracker core functionality."""

import pytest
import json
import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock, call

from fmhy_tracker import CommitProcessingError, FMHYTracker
from fmhy_tracker.tracker import ZERO_CHANGE_WARNING_THRESHOLD


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

    def test_set_commit_sha_propagates_write_errors(self, tmp_path):
        tracker = FMHYTracker(
            last_commit_sha_file=str(tmp_path / "missing" / "sha.txt")
        )

        with pytest.raises(FileNotFoundError):
            tracker.set_last_commit_sha("abc123")

    def test_set_commit_sha_preserves_previous_value_if_replace_fails(self, tmp_path):
        sha_file = tmp_path / "last_commit_sha.txt"
        sha_file.write_text("previous-sha", encoding="utf-8")
        tracker = FMHYTracker(last_commit_sha_file=str(sha_file))

        with (
            patch(
                "fmhy_tracker.storage.os.replace",
                side_effect=PermissionError("replace failed"),
            ),
            pytest.raises(PermissionError, match="replace failed"),
        ):
            tracker.set_last_commit_sha("new-sha")

        assert sha_file.read_text(encoding="utf-8") == "previous-sha"
        assert list(tmp_path.glob(".last_commit_sha.txt.*.tmp")) == []

    def test_get_last_commit_sha_strips_whitespace(self, tracker_config):
        """Test that SHA is stripped of whitespace."""
        tracker = FMHYTracker(**tracker_config)

        # Write SHA with whitespace
        with open(tracker_config["last_commit_sha_file"], "w") as f:
            f.write("  abc123def456  \n")

        result = tracker.get_last_commit_sha()
        assert result == "abc123def456"

    def test_get_last_commit_sha_rejects_empty_file(self, tracker_config):
        tracker = FMHYTracker(**tracker_config)
        with open(tracker_config["last_commit_sha_file"], "w", encoding="utf-8"):
            pass

        with pytest.raises(ValueError, match="Commit SHA file is empty"):
            tracker.get_last_commit_sha()

    def test_get_last_commit_sha_propagates_read_errors(self, tracker_config):
        tracker = FMHYTracker(**tracker_config)

        with (
            patch("builtins.open", side_effect=PermissionError("cannot read SHA")),
            pytest.raises(PermissionError, match="cannot read SHA"),
        ):
            tracker.get_last_commit_sha()


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
            pytest.raises(CommitProcessingError, match="boom"),
        ):
            tracker.run()

        assert tracker.get_last_commit_sha() is None
        mock_save_data.assert_not_called()

    @pytest.mark.parametrize("failed_output", ["generate_html", "generate_rss"])
    def test_run_fails_without_advancing_sha_when_output_generation_fails(
        self, tracker_config, sample_commit, failed_output
    ):
        tracker = FMHYTracker(**tracker_config)
        tracker.set_last_commit_sha("processed-sha")
        output_results = {
            "generate_html": True,
            "generate_rss": True,
        }
        output_results[failed_output] = False

        with (
            patch.object(tracker, "get_new_commits", return_value=[sample_commit]),
            patch.object(tracker, "process_commit", return_value=([], [])),
            patch.object(tracker, "_process_historical_commits", return_value=[]),
            patch.object(tracker, "save_data", return_value=True),
            patch.object(
                tracker, "generate_html", return_value=output_results["generate_html"]
            ),
            patch.object(
                tracker, "generate_rss", return_value=output_results["generate_rss"]
            ),
            pytest.raises(RuntimeError, match="Generated outputs failed"),
        ):
            tracker.run()

        assert tracker.get_last_commit_sha() == "processed-sha"

    def test_run_fails_when_data_save_fails(self, tracker_config, sample_commit):
        tracker = FMHYTracker(**tracker_config)
        tracker.set_last_commit_sha("processed-sha")

        with (
            patch.object(tracker, "get_new_commits", return_value=[sample_commit]),
            patch.object(tracker, "process_commit", return_value=([], [])),
            patch.object(tracker, "_process_historical_commits", return_value=[]),
            patch.object(tracker, "save_data", return_value=False),
            patch.object(tracker, "generate_html") as mock_generate_html,
            pytest.raises(RuntimeError, match="Failed to save tracker data"),
        ):
            tracker.run()

        assert tracker.get_last_commit_sha() == "processed-sha"
        mock_generate_html.assert_not_called()

    def test_run_fails_when_history_archive_cannot_be_saved(
        self, tracker_config, sample_commit
    ):
        tracker = FMHYTracker(**tracker_config)
        tracker.set_last_commit_sha("processed-sha")
        added = [
            {
                "link": "* [New resource](https://example.test)",
                "source": "video",
                "type": "new",
            }
        ]

        with (
            patch.object(tracker, "get_new_commits", return_value=[sample_commit]),
            patch.object(tracker, "process_commit", return_value=(added, [])),
            patch.object(tracker, "_process_historical_commits", return_value=[]),
            patch.object(tracker, "save_data", return_value=True),
            patch.object(
                tracker.config,
                "ensure_history_dir",
                side_effect=OSError("History storage unavailable"),
            ),
            patch.object(tracker, "generate_html") as mock_generate_html,
            pytest.raises(OSError, match="History storage unavailable"),
        ):
            tracker.run()

        assert tracker.get_last_commit_sha() == "processed-sha"
        mock_generate_html.assert_not_called()

    def test_run_propagates_commit_discovery_failure_without_replacing_data(
        self, tracker_config
    ):
        tracker = FMHYTracker(**tracker_config)
        previous_data = {"commits": [{"sha": "existing-data"}]}
        with open(tracker.output_file, "w", encoding="utf-8") as file:
            json.dump(previous_data, file)
        tracker.set_last_commit_sha("processed-sha")

        with (
            patch.object(
                tracker,
                "get_new_commits",
                side_effect=requests.ConnectionError("GitHub unavailable"),
            ),
            patch.object(tracker, "save_data") as mock_save_data,
            pytest.raises(requests.ConnectionError, match="GitHub unavailable"),
        ):
            tracker.run()

        with open(tracker.output_file, encoding="utf-8") as file:
            assert json.load(file) == previous_data
        assert tracker.get_last_commit_sha() == "processed-sha"
        mock_save_data.assert_not_called()

    def test_run_preserves_data_when_historical_commit_fetch_fails(
        self, tracker_config
    ):
        tracker = FMHYTracker(**tracker_config)
        previous_data = {"commits": [{"sha": "existing-data"}]}
        with open(tracker.output_file, "w", encoding="utf-8") as file:
            json.dump(previous_data, file)
        tracker.set_last_commit_sha("processed-sha")

        with (
            patch.object(tracker, "get_new_commits", return_value=[]),
            patch.object(
                tracker,
                "_github_get",
                side_effect=requests.ConnectionError("GitHub unavailable"),
            ),
            patch.object(tracker, "save_data") as mock_save_data,
            pytest.raises(requests.ConnectionError, match="GitHub unavailable"),
        ):
            tracker.run()

        with open(tracker.output_file, encoding="utf-8") as file:
            assert json.load(file) == previous_data
        assert tracker.get_last_commit_sha() == "processed-sha"
        mock_save_data.assert_not_called()

    def test_run_preserves_data_when_historical_commit_processing_fails(
        self, tracker_config, sample_commit
    ):
        tracker = FMHYTracker(**tracker_config)
        previous_data = {"commits": [{"sha": "existing-data"}]}
        with open(tracker.output_file, "w", encoding="utf-8") as file:
            json.dump(previous_data, file)
        tracker.set_last_commit_sha("processed-sha")

        with (
            patch.object(tracker, "get_new_commits", return_value=[]),
            patch.object(
                tracker, "get_historical_commits", return_value=[sample_commit]
            ),
            patch.object(
                tracker,
                "_github_get",
                side_effect=requests.ConnectionError("Commit details unavailable"),
            ),
            patch.object(tracker, "save_data") as mock_save_data,
            pytest.raises(CommitProcessingError, match="Commit details unavailable"),
        ):
            tracker.run()

        with open(tracker.output_file, encoding="utf-8") as file:
            assert json.load(file) == previous_data
        assert tracker.get_last_commit_sha() == "processed-sha"
        mock_save_data.assert_not_called()

    def test_run_warns_after_persisted_zero_change_streak_and_resets_on_changes(
        self, tracker_config, caplog
    ):
        tracker = FMHYTracker(**tracker_config)
        commits = [
            {
                "sha": f"commit-{index}",
                "url": f"https://example.test/commit/{index}",
                "commit": {
                    "message": "metadata update",
                    "author": {"date": "2026-11-20T00:00:00Z"},
                },
            }
            for index in range(ZERO_CHANGE_WARNING_THRESHOLD + 1)
        ]

        with (
            patch.object(tracker, "get_new_commits") as get_new_commits,
            patch.object(tracker, "process_commit", return_value=([], [])) as process,
            patch.object(tracker, "_process_historical_commits", return_value=[]),
        ):
            for commit in commits[: ZERO_CHANGE_WARNING_THRESHOLD - 1]:
                get_new_commits.return_value = [commit]
                tracker.run(generate_html=False, generate_rss=False)

            assert "consecutive upstream commits" not in caplog.text

            get_new_commits.return_value = [commits[ZERO_CHANGE_WARNING_THRESHOLD - 1]]
            tracker.run(generate_html=False, generate_rss=False)
            assert (
                f"{ZERO_CHANGE_WARNING_THRESHOLD} consecutive upstream commits"
                in caplog.text
            )

            get_new_commits.return_value = [commits[ZERO_CHANGE_WARNING_THRESHOLD]]
            process.return_value = (
                [{"link": "* [New resource](https://example.test)", "source": "video"}],
                [],
            )
            tracker.run(generate_html=False, generate_rss=False)

        with open(tracker_config["output_file"], encoding="utf-8") as file:
            data = json.load(file)
        assert data["zeroChangeStreak"] == 0
        assert data["zeroChangeStreakThroughSha"] == commits[-1]["sha"]

    def test_zero_change_streak_ignores_data_ahead_of_processed_sha(
        self, tracker_config
    ):
        tracker = FMHYTracker(**tracker_config)
        with open(tracker.output_file, "w", encoding="utf-8") as file:
            json.dump(
                {
                    "zeroChangeStreak": ZERO_CHANGE_WARNING_THRESHOLD,
                    "zeroChangeStreakThroughSha": "uncommitted-sha",
                },
                file,
            )

        assert tracker._get_zero_change_streak("processed-sha") == 0
        assert tracker._get_zero_change_streak("uncommitted-sha") == (
            ZERO_CHANGE_WARNING_THRESHOLD
        )


class TestGetNewCommits:
    """Tests for get_new_commits method."""

    def test_get_new_commits_propagates_github_request_errors(self):
        tracker = FMHYTracker()

        with (
            patch.object(
                tracker,
                "_github_get",
                side_effect=requests.ConnectionError("GitHub unavailable"),
            ),
            pytest.raises(requests.ConnectionError, match="GitHub unavailable"),
        ):
            tracker.get_new_commits("processed-sha")

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


class TestGetHistoricalCommits:
    def test_exclusions_across_more_than_one_page_keep_request_within_api_limit(self):
        tracker = FMHYTracker()
        excluded = [f"excluded-{index}" for index in range(100)]
        first_page = Mock()
        first_page.json.return_value = [{"sha": sha} for sha in excluded]
        first_page.links = {"next": {"url": "https://api.github.com/page/2"}}
        second_page = Mock()
        second_page.json.return_value = [
            {"sha": f"historical-{index}"} for index in range(5)
        ]
        second_page.links = {}

        with patch.object(
            tracker, "_github_get", side_effect=[first_page, second_page]
        ) as mock_get:
            commits = tracker.get_historical_commits(count=5, exclude_shas=excluded)

        assert [commit["sha"] for commit in commits] == [
            f"historical-{index}" for index in range(5)
        ]
        assert mock_get.call_args_list == [
            call(
                "https://api.github.com/repos/fmhy/edit/commits",
                params={"per_page": 100},
            ),
            call("https://api.github.com/page/2", params=None),
        ]

    def test_zero_count_does_not_make_a_request(self):
        tracker = FMHYTracker()
        with patch.object(tracker, "_github_get") as mock_get:
            assert tracker.get_historical_commits(count=0) == []
        mock_get.assert_not_called()

    def test_negative_count_is_rejected(self):
        tracker = FMHYTracker()
        with pytest.raises(ValueError, match="count must be non-negative"):
            tracker.get_historical_commits(count=-1)


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

    def test_save_data_replace_failure_preserves_existing_file(
        self, tracker_config, sample_tracker_data
    ):
        tracker = FMHYTracker(**tracker_config)
        output_file = Path(tracker.output_file)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        previous_data = '{"totalAdded":1}\n'
        output_file.write_text(previous_data, encoding="utf-8")

        with patch(
            "fmhy_tracker.storage.os.replace",
            side_effect=PermissionError("replace failed"),
        ):
            assert tracker.save_data(sample_tracker_data) is False

        assert output_file.read_text(encoding="utf-8") == previous_data
        assert list(output_file.parent.glob(f".{output_file.name}.*.tmp")) == []


class TestMonthlyBackfill:
    @pytest.mark.parametrize(
        "method", ["generate_monthly_data", "backfill_monthly_data"]
    )
    def test_monthly_commands_preserve_malformed_existing_archive(
        self, tmp_path, method
    ):
        tracker = FMHYTracker()
        output_file = tmp_path / "monthly_commits.json"
        previous_data = '{"month": invalid json'
        output_file.write_text(previous_data, encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            getattr(tracker, method)(str(output_file))

        assert output_file.read_text(encoding="utf-8") == previous_data

    def test_monthly_generation_propagates_malformed_source_data(self, tmp_path):
        tracker = FMHYTracker(output_file=str(tmp_path / "fmhy_data.json"))
        output_file = tmp_path / "monthly_commits.json"
        previous_data = '{"month":"2026-11","commits":[]}'
        output_file.write_text(previous_data, encoding="utf-8")
        Path(tracker.output_file).write_text("{invalid json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            tracker.generate_monthly_data(str(output_file))

        assert output_file.read_text(encoding="utf-8") == previous_data

    def test_page_failure_preserves_existing_monthly_file(self, tmp_path):
        tracker = FMHYTracker()
        output_file = tmp_path / "monthly_commits.json"
        previous_data = '{"month":"2026-11","commits":[{"sha":"existing"}]}\n'
        output_file.write_text(previous_data, encoding="utf-8")
        first_page = Mock()
        first_page.json.return_value = [{"sha": f"new-{index}"} for index in range(100)]
        first_page.links = {"next": {"url": "https://api.github.com/page/2"}}

        with (
            patch.object(
                tracker,
                "_load_monthly_commits",
                return_value=([{"sha": "existing"}], {"existing"}, False),
            ),
            patch.object(
                tracker,
                "_github_get",
                side_effect=[
                    first_page,
                    requests.ConnectionError("GitHub unavailable"),
                ],
            ),
            pytest.raises(requests.ConnectionError, match="GitHub unavailable"),
        ):
            tracker.backfill_monthly_data(str(output_file))

        assert output_file.read_text(encoding="utf-8") == previous_data

    def test_backfill_follows_next_link_after_short_page(self, tmp_path):
        tracker = FMHYTracker()
        output_file = tmp_path / "monthly_commits.json"
        month = datetime.now(timezone.utc).strftime("%Y-%m")

        def commit(sha):
            return {
                "sha": sha,
                "commit": {
                    "author": {"date": f"{month}-01T00:00:00Z"},
                    "message": f"Add {sha}",
                },
            }

        first_page = Mock()
        first_page.json.return_value = [commit("first-commit")]
        first_page.links = {"next": {"url": "https://api.github.com/page/2"}}
        second_page = Mock()
        second_page.json.return_value = [commit("second-commit")]
        second_page.links = {}

        with (
            patch.object(
                tracker,
                "_github_get",
                side_effect=[first_page, second_page],
            ) as mock_get,
            patch.object(tracker, "process_commit", return_value=([], [])),
        ):
            tracker.backfill_monthly_data(str(output_file))

        saved_data = json.loads(output_file.read_text(encoding="utf-8"))
        assert [commit["sha"] for commit in saved_data["commits"]] == [
            "first-commit",
            "second-commit",
        ]
        assert mock_get.call_args_list == [
            call(
                f"https://api.github.com/repos/{tracker.repo}/commits",
                params={"since": f"{month}-01T00:00:00Z", "per_page": 100},
            ),
            call("https://api.github.com/page/2", params=None),
        ]

    def test_monthly_write_errors_propagate(self, tmp_path):
        tracker = FMHYTracker()
        output_file = tmp_path / "missing" / "monthly_commits.json"

        with pytest.raises(FileNotFoundError):
            tracker._write_monthly_data(
                str(output_file), "2026-11", [], datetime.now(timezone.utc), 0
            )

    def test_monthly_replace_failure_preserves_existing_file(self, tmp_path):
        tracker = FMHYTracker()
        output_file = tmp_path / "monthly_commits.json"
        previous_data = '{"month":"2026-11","commits":[]}\n'
        output_file.write_text(previous_data, encoding="utf-8")

        with (
            patch(
                "fmhy_tracker.storage.os.replace",
                side_effect=PermissionError("replace failed"),
            ),
            pytest.raises(PermissionError, match="replace failed"),
        ):
            tracker._write_monthly_data(
                str(output_file), "2026-11", [], datetime.now(timezone.utc), 0
            )

        assert output_file.read_text(encoding="utf-8") == previous_data
        assert list(tmp_path.glob(".monthly_commits.json.*.tmp")) == []

    def test_commit_detail_failure_preserves_existing_monthly_file(self, tmp_path):
        tracker = FMHYTracker()
        output_file = tmp_path / "monthly_commits.json"
        previous_data = '{"month":"2026-11","commits":[{"sha":"existing"}]}\n'
        output_file.write_text(previous_data, encoding="utf-8")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        commit_list_response = Mock()
        commit_list_response.json.return_value = [
            {
                "sha": "new-commit",
                "url": "https://api.github.com/repos/example/commit/new-commit",
                "commit": {
                    "author": {"date": f"{month}-01T00:00:00Z"},
                    "message": "Add a resource",
                },
            }
        ]
        commit_list_response.links = {}

        with (
            patch.object(
                tracker,
                "_load_monthly_commits",
                return_value=([{"sha": "existing"}], {"existing"}, False),
            ),
            patch.object(
                tracker,
                "_github_get",
                side_effect=[
                    commit_list_response,
                    requests.ConnectionError("Commit details unavailable"),
                ],
            ),
            pytest.raises(CommitProcessingError, match="Commit details unavailable"),
        ):
            tracker.backfill_monthly_data(str(output_file))

        assert output_file.read_text(encoding="utf-8") == previous_data


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

    def test_get_history_propagates_malformed_archive(self, tmp_path):
        tracker = FMHYTracker()
        tracker.config.history_dir = str(tmp_path)
        (tmp_path / "fmhy_data_corrupt.json").write_text("{invalid", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            tracker.get_history()

    def test_get_history_zero_limit_returns_empty_without_reading_archives(
        self, tmp_path
    ):
        tracker = FMHYTracker()
        tracker.config.history_dir = str(tmp_path)
        (tmp_path / "fmhy_data_corrupt.json").write_text("{invalid", encoding="utf-8")

        assert tracker.get_history(limit=0) == []

    def test_get_history_rejects_negative_limit(self):
        tracker = FMHYTracker()

        with pytest.raises(ValueError, match="limit must be non-negative"):
            tracker.get_history(limit=-1)

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

    def test_history_replace_failure_preserves_existing_archive(
        self, sample_tracker_data
    ):
        tracker = FMHYTracker()
        tracker.config.ensure_history_dir()
        history_file = (
            tracker.config.history_path / "fmhy_data_2026-11-20_12-00-00.json"
        )
        previous_data = '{"totalAdded":1}\n'
        history_file.write_text(previous_data, encoding="utf-8")

        with (
            patch(
                "fmhy_tracker.storage.os.replace",
                side_effect=PermissionError("replace failed"),
            ),
            pytest.raises(PermissionError, match="replace failed"),
        ):
            tracker.save_history(sample_tracker_data)

        assert history_file.read_text(encoding="utf-8") == previous_data
        assert list(history_file.parent.iterdir()) == [history_file]

    def test_history_saves_within_one_second_keep_all_snapshots(
        self, sample_tracker_data
    ):
        tracker = FMHYTracker()
        tracker.config.ensure_history_dir()
        saved_times = iter(
            [
                datetime(2026, 11, 20, 12, 0, 0, 100, tzinfo=timezone.utc),
                datetime(2026, 11, 20, 12, 0, 0, 100, tzinfo=timezone.utc),
                datetime(2026, 11, 20, 12, 0, 0, 200, tzinfo=timezone.utc),
            ]
        )

        class FixedDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return next(saved_times)

        legacy_file = tracker.config.history_path / "fmhy_data_2026-11-20_12-00-00.json"
        legacy_file.write_text('{"totalAdded":0}', encoding="utf-8")

        with patch("fmhy_tracker.tracker.datetime", FixedDateTime):
            for total in (1, 2, 3):
                tracker.save_history({**sample_tracker_data, "totalAdded": total})

        history = tracker.get_history(limit=10)
        totals = [snapshot["totalAdded"] for snapshot in history]
        assert totals[0] == 3
        assert sorted(totals[1:3]) == [1, 2]
        assert totals[3:] == [0]

    def test_save_history_with_zero_limit_keeps_only_existing_archives(
        self, monkeypatch, sample_tracker_data
    ):
        tracker = FMHYTracker()
        tracker.config.ensure_history_dir()
        archive = tracker.config.history_path / "fmhy_data_2026-11-20_12-00-00.json"
        archive.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(tracker.config, "max_history_files", 0)

        tracker.save_history(sample_tracker_data)

        assert list(tracker.config.history_path.iterdir()) == [archive]
        assert archive.read_text(encoding="utf-8") == "{}"

    def test_save_history_rejects_negative_limit(
        self, monkeypatch, sample_tracker_data
    ):
        tracker = FMHYTracker()
        monkeypatch.setattr(tracker.config, "max_history_files", -1)

        with pytest.raises(ValueError, match="FMHY_MAX_HISTORY must be non-negative"):
            tracker.save_history(sample_tracker_data)

        assert not tracker.config.history_path.exists()

    def test_save_history_with_positive_limit_keeps_newest_archive(
        self, monkeypatch, sample_tracker_data
    ):
        tracker = FMHYTracker()
        tracker.config.ensure_history_dir()
        archive = tracker.config.history_path / "fmhy_data_2000-01-01_00-00-00.json"
        archive.write_text("{}", encoding="utf-8")
        monkeypatch.setattr(tracker.config, "max_history_files", 1)

        tracker.save_history(sample_tracker_data)

        assert not archive.exists()
        assert len(tracker.get_history()) == 1
        assert len(list(tracker.config.history_path.iterdir())) == 1
