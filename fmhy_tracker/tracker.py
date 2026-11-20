"""FMHY Tracker - Monitor changes in the FMHY repository."""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Any

import requests

from .html_generator import HTMLGenerator
from .rss_generator import RSSGenerator
from .config import config

logger = logging.getLogger(__name__)


class GitHubRateLimitError(requests.RequestException):
    """Raised when GitHub indicates the API rate limit has been exhausted."""


class CommitProcessingError(RuntimeError):
    """Raised when a commit cannot be processed safely."""


class FMHYTracker:
    """Track changes in the FMHY repository."""

    def __init__(
        self,
        repo: str = None,
        folder_path: str = None,
        last_commit_sha_file: str = None,
        output_file: str = None,
        runtime_config=None,
    ):
        """Initialize the FMHY Tracker.

        Args:
            repo: GitHub repository to monitor (default: fmhy/edit)
            folder_path: Folder path to monitor for changes (default: docs/)
            last_commit_sha_file: File to store the last processed commit SHA
            output_file: Output JSON file path
        """
        self.config = runtime_config or config
        self.repo = repo or self.config.repo
        self.folder_path = folder_path or self.config.folder_path
        self.last_commit_sha_file = (
            last_commit_sha_file or self.config.last_commit_sha_file
        )
        self.output_file = output_file or self.config.output_file
        self.request_timeout = self.config.github_timeout_seconds
        self.request_retries = self.config.github_retries

        # Set up GitHub API headers (with token if available for higher rate limits)
        self.github_headers = {}
        github_token = self.config.github_token
        if github_token:
            self.github_headers["Authorization"] = f"token {github_token}"

        self.html_generator = HTMLGenerator()
        self.rss_generator = RSSGenerator(repo=self.repo, runtime_config=self.config)

    def _utc_now_iso(self) -> str:
        """Return a timezone-aware UTC timestamp for generated data files."""
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def _raise_for_status(self, response: requests.Response) -> None:
        """Raise a helpful exception for GitHub HTTP failures."""
        status_code = getattr(response, "status_code", None)
        headers = getattr(response, "headers", {}) or {}
        remaining = headers.get("X-RateLimit-Remaining")
        if status_code in {403, 429} and remaining == "0":
            reset_at = headers.get("X-RateLimit-Reset")
            message = "GitHub API rate limit exceeded"
            if reset_at:
                try:
                    reset_time = datetime.fromtimestamp(
                        int(reset_at), tz=timezone.utc
                    ).isoformat()
                    message = f"{message}; resets at {reset_time}"
                except ValueError:
                    message = f"{message}; reset header was {reset_at!r}"
            raise GitHubRateLimitError(message, response=response)

        response.raise_for_status()

    def _github_get(self, url: str, **kwargs) -> requests.Response:
        """GET a GitHub API URL with timeout, retries, and rate-limit errors."""
        last_error = None
        for attempt in range(self.request_retries + 1):
            try:
                response = requests.get(
                    url,
                    headers=self.github_headers,
                    timeout=self.request_timeout,
                    **kwargs,
                )
                self._raise_for_status(response)
                return response
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.request_retries:
                    raise
                delay = min(2**attempt, 8)
                logger.warning(
                    "GitHub request failed for %s (%s); retrying in %ss",
                    url,
                    exc,
                    delay,
                )
                time.sleep(delay)

        raise last_error

    def get_last_commit_sha(self) -> Optional[str]:
        """Get the last processed commit SHA from file.

        Returns:
            The last commit SHA or None if not found
        """
        if os.path.exists(self.last_commit_sha_file):
            try:
                with open(self.last_commit_sha_file, "r") as f:
                    return f.read().strip()
            except Exception as e:
                logger.error("Error reading commit SHA file: %s", e)
                return None
        return None

    def set_last_commit_sha(self, sha: str) -> None:
        """Save the last processed commit SHA to file.

        Args:
            sha: The commit SHA to save
        """
        try:
            with open(self.last_commit_sha_file, "w") as f:
                f.write(sha)
        except Exception as e:
            logger.error("Error writing commit SHA file: %s", e)

    def get_new_commits(self, last_commit_sha: Optional[str]) -> List[Dict]:
        """Fetch new commits from the repository.

        Args:
            last_commit_sha: The last processed commit SHA

        Returns:
            List of new commits (oldest first)
        """
        try:
            url = f"https://api.github.com/repos/{self.repo}/commits"
            params = {"per_page": 100}
            new_commits = []

            while url:
                response = self._github_get(
                    url,
                    params=params,
                )
                commits = response.json()

                if not commits:
                    break

                if last_commit_sha is None:
                    return [commits[0]]

                for commit in commits:
                    if commit["sha"] == last_commit_sha:
                        return list(reversed(new_commits))
                    new_commits.append(commit)

                url = response.links.get("next", {}).get("url")
                params = None

            return list(reversed(new_commits))
        except requests.RequestException as e:
            logger.error("Error fetching commits: %s", e)
            return []
        except Exception as e:
            logger.exception("Unexpected error fetching commits: %s", e)
            return []

    def get_historical_commits(
        self, count: int = 5, exclude_shas: List[str] = None
    ) -> List[Dict]:
        """Fetch historical commits from the repository.

        Args:
            count: Number of commits to fetch
            exclude_shas: List of commit SHAs to exclude (already processed)

        Returns:
            List of historical commits
        """
        try:
            exclude_shas = exclude_shas or []
            # Fetch more commits than needed to account for exclusions
            fetch_count = count + len(exclude_shas)
            url = f"https://api.github.com/repos/{self.repo}/commits?per_page={fetch_count}"
            response = self._github_get(url)
            commits = response.json()

            # Filter out excluded commits
            if exclude_shas:
                commits = [c for c in commits if c["sha"] not in exclude_shas]

            return commits[:count]
        except requests.RequestException as e:
            logger.error("Error fetching historical commits: %s", e)
            return []
        except Exception as e:
            logger.exception("Unexpected error fetching historical commits: %s", e)
            return []

    def extract_link_identifier(self, markdown_link: str) -> str:
        """Extract link title from a markdown link for comparison.

        This uses the link title (text between []) as the identifier rather than
        the domain, so that URL changes are correctly detected as updates.

        Args:
            markdown_link: Markdown formatted link

        Returns:
            Extracted link title or normalized markdown text
        """
        clean_link = markdown_link.strip().lstrip("*").strip()
        clean_link = re.sub(r"^⭐\s*", "", clean_link)

        title_match = re.search(r"\[([^\]]+)\]", clean_link)
        if title_match:
            title = title_match.group(1)
            title = re.sub(r"\*\*(.+?)\*\*", r"\1", title)
            title = re.sub(r"__(.+?)__", r"\1", title)
            return title.lower().strip()

        return clean_link.lower()

    def categorize_links(
        self, added_links: List[Dict], removed_links: List[Dict]
    ) -> Tuple[List[Dict], List[Dict]]:
        """Categorize links as new, removed, or updated.

        Args:
            added_links: List of added link dictionaries
            removed_links: List of removed link dictionaries

        Returns:
            Tuple of (categorized_added, categorized_removed)
        """
        categorized_added = []
        categorized_removed = []

        removed_map = {}
        for item in removed_links:
            identifier = self.extract_link_identifier(item["link"])
            removed_map[identifier] = item

        added_map = {}
        for item in added_links:
            identifier = self.extract_link_identifier(item["link"])
            added_map[identifier] = item

        for item in added_links:
            identifier = self.extract_link_identifier(item["link"])
            if identifier in removed_map:
                categorized_item = item.copy()
                categorized_item["type"] = "updated"
                categorized_item["relatedLink"] = removed_map[identifier]["link"]
                categorized_added.append(categorized_item)
            else:
                categorized_item = item.copy()
                categorized_item["type"] = "new"
                categorized_added.append(categorized_item)

        for item in removed_links:
            identifier = self.extract_link_identifier(item["link"])
            if identifier not in added_map:
                categorized_item = item.copy()
                categorized_item["type"] = "removed"
                categorized_removed.append(categorized_item)

        return categorized_added, categorized_removed

    def _extract_link_title(self, markdown_link: str) -> str:
        """Extract title from markdown link.

        Args:
            markdown_link: Markdown formatted link

        Returns:
            Extracted title or the original link
        """
        match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", markdown_link)
        if match:
            return match.group(1)
        return markdown_link

    def process_commit(
        self, commit: Dict, raise_on_error: bool = False
    ) -> Tuple[List[Dict], List[Dict]]:
        """Process a single commit and extract changes.

        Args:
            commit: Commit data dictionary
            raise_on_error: Raise CommitProcessingError instead of returning empty
                results when the commit cannot be fetched or parsed.

        Returns:
            Tuple of (added_links, removed_links)
        """
        try:
            commit_url = commit["url"]
            response = self._github_get(commit_url)
            commit_data = response.json()

            added_links = []
            removed_links = []

            commit_message = commit["commit"]["message"].lower()
            if any(keyword in commit_message for keyword in ["create"]):
                has_meaningful_changes = False
                for file in commit_data.get("files", []):
                    if file["filename"].startswith(self.folder_path) and file[
                        "filename"
                    ].endswith(".md"):
                        patch = file.get("patch")
                        if patch and any(
                            (line.startswith("+") or line.startswith("-"))
                            and "*" in line
                            for line in patch.split("\n")
                        ):
                            has_meaningful_changes = True
                            break

                if not has_meaningful_changes:
                    return [], []

            for file in commit_data.get("files", []):
                if file["filename"].startswith(self.folder_path) and file[
                    "filename"
                ].endswith(".md"):
                    filename = file["filename"]
                    source = filename.replace(self.folder_path, "").replace(".md", "")

                    patch = file.get("patch")
                    if patch:
                        for line in patch.split("\n"):
                            # Only parse lines that start with "* " (asterisk followed by space)
                            stripped_line = line[1:].strip()
                            if line.startswith("+") and stripped_line.startswith("* "):
                                added_links.append(
                                    {"link": stripped_line, "source": source}
                                )
                            elif line.startswith("-") and stripped_line.startswith(
                                "* "
                            ):
                                removed_links.append(
                                    {"link": stripped_line, "source": source}
                                )

            categorized_added, categorized_removed = self.categorize_links(
                added_links, removed_links
            )
            return categorized_added, categorized_removed
        except requests.RequestException as e:
            message = f"Error processing commit {commit.get('sha', 'unknown')}: {e}"
            logger.error(message)
            if raise_on_error:
                raise CommitProcessingError(message) from e
            return [], []
        except Exception as e:
            message = (
                f"Unexpected error processing commit "
                f"{commit.get('sha', 'unknown')}: {e}"
            )
            logger.exception(message)
            if raise_on_error:
                raise CommitProcessingError(message) from e
            return [], []

    def save_data(self, data: Dict) -> bool:
        """Save data to JSON file.

        Args:
            data: Data dictionary to save

        Returns:
            True when the data was written successfully.
        """
        try:
            with open(self.output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("Data saved to %s", self.output_file)
            return True
        except Exception as e:
            logger.error("Error saving data to file: %s", e)
            return False

    def save_history(self, data: Dict) -> None:
        """Save data to history archive.

        Args:
            data: Data dictionary to archive
        """
        try:
            self.config.ensure_history_dir()
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
            history_file = self.config.history_path / f"fmhy_data_{timestamp}.json"

            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info("History saved to %s", history_file)

            self._cleanup_history()
        except Exception as e:
            logger.error("Error saving history: %s", e)

    def _cleanup_history(self, max_files: int = None) -> None:
        """Clean up old history files.

        Args:
            max_files: Maximum number of history files to keep (default from config)
        """
        if max_files is None:
            max_files = self.config.max_history_files
        try:
            history_files = sorted(self.config.history_path.glob("fmhy_data_*.json"))
            if len(history_files) > max_files:
                for old_file in history_files[:-max_files]:
                    old_file.unlink()
                    logger.info("Cleaned up old history file: %s", old_file)
        except Exception as e:
            logger.error("Error cleaning up history: %s", e)

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get historical data files.

        Args:
            limit: Maximum number of history entries to return

        Returns:
            List of historical data dictionaries
        """
        history = []
        try:
            if not self.config.history_path.exists():
                return []

            history_files = sorted(
                self.config.history_path.glob("fmhy_data_*.json"), reverse=True
            )[:limit]

            for history_file in history_files:
                try:
                    with open(history_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        data["_filename"] = history_file.name
                        history.append(data)
                except Exception as e:
                    logger.error("Error reading history file %s: %s", history_file, e)
        except Exception as e:
            logger.error("Error getting history: %s", e)

        return history

    def show_history(self) -> None:
        """Display historical data summary."""
        history = self.get_history(limit=10)

        if not history:
            print("No history found.")
            return

        print("\n=== FMHY Tracker History ===\n")
        for i, entry in enumerate(history, 1):
            print(f"{i}. {entry.get('_filename', 'Unknown')}")
            print(f"   Updated: {entry.get('lastUpdated', 'N/A')}")
            print(
                f"   New: {entry.get('totalNew', 0)}, "
                f"Updated: {entry.get('totalUpdated', 0)}, "
                f"Removed: {entry.get('totalRemoved', 0)}"
            )
            print(f"   Commits: {entry.get('totalCommits', 0)}")
            print()

    def load_existing_monthly_data(self, output_file: str = None) -> Dict:
        """Load existing monthly data from file.

        Args:
            output_file: Path to monthly output file

        Returns:
            Existing monthly data or empty structure
        """
        if output_file is None:
            output_file = self.config.monthly_output_file

        try:
            if Path(output_file).exists():
                with open(output_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.error("Error loading existing monthly data: %s", e)

        return {"month": "", "commits": [], "totalCommits": 0}

    def get_current_month_commits_from_data(self) -> List[Dict]:
        """Get commits from fmhy_data.json that are from the current month.

        Returns:
            List of commits from current month
        """
        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month
        month_prefix = f"{year}-{month:02d}"

        commits = []
        try:
            if Path(self.output_file).exists():
                with open(self.output_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for commit in data.get("commits", []):
                    commit_date = commit.get("date", "")
                    if commit_date.startswith(month_prefix):
                        commits.append(commit)
        except Exception as e:
            logger.error("Error reading current data: %s", e)

        return commits

    def _get_date_group(self, date_string: str) -> str:
        """Determine the date group for a commit.

        Args:
            date_string: ISO format date string

        Returns:
            Date group: "today", "yesterday", "thisWeek", or "earlier"
        """
        try:
            commit_date = datetime.fromisoformat(date_string.replace("Z", "+00:00"))
            now = (
                datetime.now(commit_date.tzinfo)
                if commit_date.tzinfo
                else datetime.now(timezone.utc).replace(tzinfo=None)
            )

            # Get start of today
            today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - timedelta(days=1)
            week_start = today_start - timedelta(days=7)

            if commit_date >= today_start:
                return "today"
            elif commit_date >= yesterday_start:
                return "yesterday"
            elif commit_date >= week_start:
                return "thisWeek"
            else:
                return "earlier"
        except Exception:
            return "earlier"

    def generate_monthly_data(self, output_file: str = None) -> None:
        """Incrementally update monthly commits JSON file.

        This method merges commits from fmhy_data.json into the existing
        monthly_commits.json file, preserving previously saved commits.

        Args:
            output_file: Path to output file (default from config)
        """
        if output_file is None:
            output_file = self.config.monthly_output_file

        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month
        current_month = f"{year}-{month:02d}"

        logger.info("Updating monthly data for %s...", current_month)

        # Load existing monthly data (resetting if the month rolled over)
        existing_commits, existing_shas, is_new_month = self._load_monthly_commits(
            output_file, current_month
        )
        if is_new_month:
            logger.info("New month detected, starting fresh monthly data...")

        # Get commits from current fmhy_data.json that are from this month
        current_commits = self.get_current_month_commits_from_data()

        # Merge new commits (add any that aren't already in the monthly file)
        new_count = 0
        for commit in current_commits:
            sha = commit.get("sha")
            if sha and sha not in existing_shas:
                # Mark as monthly historical and add dateGroup
                commit_copy = commit.copy()
                commit_copy["isMonthlyHistorical"] = True
                commit_copy.pop("isHistorical", None)  # Remove if present
                commit_copy["dateGroup"] = self._get_date_group(commit.get("date", ""))
                existing_commits.append(commit_copy)
                existing_shas.add(sha)
                new_count += 1

        self._write_monthly_data(
            output_file, current_month, existing_commits, now, new_count
        )

    def backfill_monthly_data(self, output_file: str = None) -> None:
        """Backfill monthly data with all historical commits from the current month.

        This fetches ALL commits from the beginning of the current month
        and processes them to populate the monthly_commits.json file.

        Args:
            output_file: Path to output file (default from config)
        """
        if output_file is None:
            output_file = self.config.monthly_output_file

        now = datetime.now(timezone.utc)
        year = now.year
        month = now.month
        current_month = f"{year}-{month:02d}"

        # Calculate start of month
        month_start = f"{year}-{month:02d}-01T00:00:00Z"

        logger.info("Backfilling monthly data for %s...", current_month)
        logger.info("Fetching all commits since %s...", month_start)

        # Load existing monthly data (resetting if the month rolled over)
        existing_commits, existing_shas, _ = self._load_monthly_commits(
            output_file, current_month
        )

        # Fetch all commits from the start of the month
        all_commits = []
        page = 1
        per_page = 100

        while True:
            try:
                url = f"https://api.github.com/repos/{self.repo}/commits"
                params = {"since": month_start, "per_page": per_page, "page": page}
                response = self._github_get(url, params=params)
                commits = response.json()

                if not commits:
                    break

                all_commits.extend(commits)
                logger.info("  Fetched page %s: %s commits", page, len(commits))

                if len(commits) < per_page:
                    break

                page += 1
            except requests.RequestException as e:
                logger.error("Error fetching commits page %s: %s", page, e)
                break

        logger.info("Total commits fetched: %s", len(all_commits))

        # Process each commit that isn't already in the monthly data
        new_count = 0
        for commit in all_commits:
            sha = commit.get("sha")
            if sha in existing_shas:
                continue

            commit_date = commit.get("commit", {}).get("author", {}).get("date", "")

            # Skip if not from current month (API might return older commits)
            if not commit_date.startswith(current_month):
                continue

            logger.info(
                "Processing: %s - %s...",
                sha[:8],
                commit.get("commit", {}).get("message", "")[:50],
            )

            try:
                added, removed = self.process_commit(commit)

                commit_data = {
                    "sha": sha,
                    "date": commit_date,
                    "message": commit.get("commit", {}).get("message", ""),
                    "added": added,
                    "removed": removed,
                    "isMonthlyHistorical": True,
                    "dateGroup": self._get_date_group(commit_date),
                }

                existing_commits.append(commit_data)
                existing_shas.add(sha)
                new_count += 1
            except Exception as e:
                logger.error("  Error processing commit %s: %s", sha[:8], e)
                continue

        self._write_monthly_data(
            output_file, current_month, existing_commits, now, new_count
        )

    def _load_monthly_commits(
        self, output_file: str, current_month: str
    ) -> Tuple[List[Dict], set, bool]:
        """Load monthly commits, resetting when the stored month has rolled over.

        Returns (existing_commits, existing_shas, is_new_month).
        """
        existing_data = self.load_existing_monthly_data(output_file)
        is_new_month = existing_data.get("month") != current_month
        existing_commits = [] if is_new_month else existing_data.get("commits", [])
        existing_shas = {c.get("sha") for c in existing_commits}
        return existing_commits, existing_shas, is_new_month

    def _write_monthly_data(
        self,
        output_file: str,
        current_month: str,
        commits: List[Dict],
        now: datetime,
        new_count: int,
    ) -> None:
        """Recompute date groups, sort newest-first, and persist monthly data."""
        # Update dateGroup for all commits (in case time has passed)
        for commit in commits:
            commit["dateGroup"] = self._get_date_group(commit.get("date", ""))

        sorted_commits = sorted(commits, key=lambda c: c.get("date", ""), reverse=True)

        data = {
            "month": current_month,
            "generatedAt": now.isoformat().replace("+00:00", "Z"),
            "totalCommits": len(sorted_commits),
            "commits": sorted_commits,
        }

        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            logger.info(
                "Monthly data saved to %s (%s total commits, %s new)",
                output_file,
                len(sorted_commits),
                new_count,
            )
        except Exception as e:
            logger.error("Error saving monthly data: %s", e)

    def _build_commit_data(
        self,
        commit: Dict,
        added: List[Dict],
        removed: List[Dict],
        *,
        is_historical: bool,
    ) -> Dict:
        """Build the standard per-commit data dict shared across run/backfill."""
        return {
            "sha": commit["sha"],
            "date": commit["commit"]["author"]["date"],
            "message": commit["commit"]["message"],
            "added": added,
            "removed": removed,
            "isHistorical": is_historical,
        }

    def _process_historical_commits(
        self, count: int, exclude_shas: List[str] = None
    ) -> List[Dict]:
        """Fetch historical commits and build display-ready commit dicts."""
        historical_commits = self.get_historical_commits(
            count=count, exclude_shas=exclude_shas
        )
        commits_data = []
        for commit in historical_commits:
            logger.info(
                "Processing historical commit: %s - %s",
                commit["sha"][:8],
                commit["commit"]["message"],
            )
            added, removed = self.process_commit(commit)
            commits_data.append(
                self._build_commit_data(commit, added, removed, is_historical=True)
            )
        return commits_data

    @staticmethod
    def _type_prefix(link_type: str) -> str:
        """Return the log prefix for an added link's change type."""
        if link_type == "new":
            return "[NEW]"
        if link_type == "updated":
            return "[UPDATED]"
        return ""

    def _log_commit_changes(
        self, added: List[Dict], removed: List[Dict]
    ) -> Tuple[int, int, int, int]:
        """Log added/removed links; return (added, new, updated, removed) counts."""
        total_new = 0
        total_updated = 0
        if added:
            logger.info("  Added %s link(s):", len(added))
            for item in added:
                link_type = item.get("type", "new")
                logger.info(
                    "    [+] %s [%s] %s",
                    self._type_prefix(link_type),
                    item["source"],
                    item["link"],
                )
                if link_type == "new":
                    total_new += 1
                elif link_type == "updated":
                    total_updated += 1
        if removed:
            logger.info("  Removed %s link(s):", len(removed))
            for item in removed:
                logger.info("    [-] [%s] %s", item["source"], item["link"])
        return len(added), total_new, total_updated, len(removed)

    def run(self, generate_html: bool = True, generate_rss: bool = True) -> None:
        """Run the tracker to process new commits."""
        logger.info("Starting FMHY tracker...")
        last_commit_sha = self.get_last_commit_sha()
        logger.info("Last processed commit SHA: %s", last_commit_sha)

        try:
            new_commits = list(self.get_new_commits(last_commit_sha))
            logger.info("Found %s new commits.", len(new_commits))
        except Exception as e:
            logger.error("Error getting new commits: %s", e)
            return

        if not new_commits:
            logger.info("No new commits found.")

            # Even with no new commits, we should display historical commits
            min_commits = self.config.min_commits
            logger.info(
                "Fetching %s historical commit(s) to meet minimum display requirement...",
                min_commits,
            )

            commits_data = self._process_historical_commits(count=min_commits)

            # Stats are 0 since these are all historical (no new updates)
            data = {
                "lastUpdated": self._utc_now_iso(),
                "totalAdded": 0,
                "totalRemoved": 0,
                "totalNew": 0,
                "totalUpdated": 0,
                "totalCommits": len(commits_data),
                "commits": commits_data,
            }

            if not self.save_data(data):
                return

            html_generated = self.generate_html() if generate_html else True
            rss_generated = self.generate_rss() if generate_rss else True

            # Initialize last commit SHA if not set
            if (
                last_commit_sha is None
                and commits_data
                and html_generated
                and rss_generated
            ):
                latest_sha = commits_data[0]["sha"]
                self.set_last_commit_sha(latest_sha)
                logger.info("Initialized last commit SHA to latest: %s", latest_sha[:8])

            logger.info(
                "Generated output with %s historical commit(s)", len(commits_data)
            )
            return

        data = {
            "lastUpdated": self._utc_now_iso(),
            "totalAdded": 0,
            "totalRemoved": 0,
            "totalNew": 0,
            "totalUpdated": 0,
            "totalCommits": len(new_commits),
            "commits": [],
        }

        latest_sha = None
        total_added = 0
        total_removed = 0
        total_new = 0
        total_updated = 0
        commits_data = []

        for commit in new_commits:
            logger.info(
                "\nProcessing commit: %s - %s",
                commit["sha"][:8],
                commit["commit"]["message"],
            )
            try:
                added, removed = self.process_commit(commit, raise_on_error=True)
            except CommitProcessingError:
                logger.error(
                    "Stopping before updating %s so the failed commit can be retried.",
                    self.last_commit_sha_file,
                )
                return

            commits_data.append(
                self._build_commit_data(commit, added, removed, is_historical=False)
            )

            added_count, new_count, updated_count, removed_count = (
                self._log_commit_changes(added, removed)
            )
            total_added += added_count
            total_new += new_count
            total_updated += updated_count
            total_removed += removed_count

            latest_sha = commit["sha"]

        logger.info(
            "\nSummary: %s links added (%s new, %s updated), %s links removed",
            total_added,
            total_new,
            total_updated,
            total_removed,
        )

        # Ensure minimum commits are displayed
        min_commits = self.config.min_commits
        if len(commits_data) < min_commits:
            needed = min_commits - len(commits_data)
            logger.info(
                "\nFetching %s historical commit(s) to meet minimum of %s...",
                needed,
                min_commits,
            )

            # Get SHAs of already processed commits
            processed_shas = [c["sha"] for c in commits_data]

            # Fetch historical commits (their stats are not added to totals;
            # stats only reflect new commits)
            historical_data = self._process_historical_commits(
                count=needed, exclude_shas=processed_shas
            )
            commits_data.extend(historical_data)

            logger.info("Added %s historical commit(s)", len(historical_data))

        data["totalAdded"] = total_added
        data["totalRemoved"] = total_removed
        data["totalNew"] = total_new
        data["totalUpdated"] = total_updated
        data["totalCommits"] = len(commits_data)
        data["commits"] = commits_data

        if not self.save_data(data):
            return

        # Save to history
        if total_added > 0 or total_removed > 0:
            self.save_history(data)

        html_generated = self.generate_html() if generate_html else True
        rss_generated = self.generate_rss() if generate_rss else True

        if latest_sha and html_generated and rss_generated:
            self.set_last_commit_sha(latest_sha)
            logger.info("Updated last commit SHA to: %s", latest_sha[:8])
        elif latest_sha:
            logger.error(
                "Generated outputs failed, so %s was not advanced.",
                self.last_commit_sha_file,
            )

    def generate_html(self, output_file: str = "index.html") -> bool:
        """Generate HTML report from the latest data.

        Args:
            output_file: Path to output HTML file

        Returns:
            True when the HTML file was generated successfully.
        """
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.html_generator.generate(
                data, output_file, monthly_file=self.config.monthly_output_file
            )
            return True
        except FileNotFoundError:
            logger.error("Data file not found: %s", self.output_file)
            return False
        except Exception as e:
            logger.error("Error generating HTML: %s", e)
            return False

    def generate_rss(self, output_file: str = "feed.xml") -> bool:
        """Generate RSS feed from the latest data.

        Args:
            output_file: Path to output RSS file

        Returns:
            True when the RSS file was generated successfully.
        """
        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            self.rss_generator.generate(data, output_file)
            return True
        except FileNotFoundError:
            logger.error("Data file not found: %s", self.output_file)
            return False
        except Exception as e:
            logger.error("Error generating RSS: %s", e)
            return False
