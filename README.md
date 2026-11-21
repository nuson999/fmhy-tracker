# FMHY Tracker

A Python utility to track changes in the FMHY (Free Media Heaven) repository, with an HTML dashboard and RSS feed.

## Purpose

This tool monitors the [fmhy/edit](https://github.com/fmhy/edit) repository for commits and identifies:

- Newly added links
- Updated links, such as title-preserving URL changes
- Removed links

It's particularly useful for staying up-to-date with new resources added to the FMHY collection.

## Features

- Tracks commits to the fmhy/edit repository
- Parses commit diffs to identify added, updated, and removed markdown list links
- Maintains state using a commit SHA file to avoid duplicate processing
- Uses GitHub request timeouts, retries, and rate-limit-aware errors
- Provides clear output of changes with commit messages
- Generates RSS 2.0 feed for tracking changes
- RSS feed includes all commits with detailed link changes
- Autodiscovery support for RSS readers
- Avoids advancing the stored commit SHA when new commit processing fails
- Warns in the run log after 10 consecutive upstream commits produce no classified link changes

## Installation

1. Clone this repository:

   ```bash
   git clone https://github.com/nuson999/fmhy-tracker.git
   cd fmhy-tracker
   ```

2. Install dependencies:

   ```bash
   pip install -e .
   ```

   For development and tests:

   ```bash
   pip install -e ".[dev]"
   ```

## Usage

### Command Line

```bash
python main.py
```

### As a Module

```python
from fmhy_tracker import FMHYTracker

tracker = FMHYTracker()
tracker.run()
```

## How It Works

1. The tracker fetches the latest commits from the fmhy/edit repository
2. It compares the commits with the last processed commit (stored in `last_commit_sha.txt`)
3. For each new commit, it analyzes the diff to find:
   - Lines starting with "+" that contain markdown list links
   - Lines starting with "-" that contain markdown list links
4. It categorizes same-title removals/additions as updates
5. It outputs the changes, generates the HTML dashboard and RSS feed, and updates the last processed commit SHA only after new commits process successfully

## Configuration

You can customize the tracker by modifying the constructor parameters:

- `repo`: The GitHub repository to monitor (default: "fmhy/edit")
- `folder_path`: The folder path to monitor for changes (default: "docs/")
- `last_commit_sha_file`: The file to store the last processed commit SHA (default: "last_commit_sha.txt")

Environment variables are also supported:

- `FMHY_REPO`
- `FMHY_FOLDER_PATH`
- `FMHY_OUTPUT_FILE`
- `FMHY_LAST_COMMIT_SHA_FILE`
- `FMHY_HISTORY_DIR`
- `FMHY_MIN_COMMITS`
- `FMHY_MAX_HISTORY` (default: `100`; `0` stops creating snapshots and preserves existing archives; negative values are invalid)
- `FMHY_MONTHLY_OUTPUT`
- `FMHY_GITHUB_TIMEOUT_SECONDS`
- `FMHY_GITHUB_RETRIES`
- `GITHUB_TOKEN`

Timeouts must be positive. Retry counts, minimum displayed commits, and retained history counts must
be non-negative. Invalid values use their documented defaults and emit a warning.

### RSS Feed

The tracker automatically generates an RSS 2.0 feed at `feed.xml`.

**Subscribing to the feed:**

- Feed URL: `https://fmhy-tracker.pages.dev/feed.xml`
- The feed is updated every 6 hours automatically
- Each RSS item represents one commit with all its changes

**Using the feed:**

- Subscribe in your favorite RSS reader (Feedly, NewsBlur, etc.)
- RSS items link to the corresponding GitHub commit for full context
- Click the SHA link in descriptions to view the commit on GitHub

**Skip RSS generation:**

```bash
python main.py --no-rss
```

## GitHub Actions

This repository includes a GitHub Actions workflow that runs every 6 hours to monitor for changes. To use it:

1. Fork this repository
2. Enable GitHub Actions in your fork
3. The workflow will automatically run tests/lint checks, update generated tracker files, and deploy the static dashboard

To summarize recent monitor and Pages runs locally (requires the GitHub CLI to be authenticated):

```bash
fmhy-run-health --limit 10
```

The report counts completed runs only when at least one job started. Runs with no started jobs,
including Actions spending-limit blocks, are listed separately and excluded from the success rate.
Failed runs include the conclusion and names of jobs that failed, timed out, or were cancelled;
skipped jobs are omitted.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Dashboard behavior

- Pages contain up to 50 matching change rows, grouped by commit.
- Compact date headings keep resource names and change labels prominent; commit messages and GitHub links remain available.
- Pagination appears below results, with page buttons, a direct page input, and shareable `page` URLs. Changing a filter resets the page.
- Type counts respect search, category, starred, and history selection, ignoring the selected type so alternatives can be compared.
- Category counts respect search, type, starred, and history selection, ignoring the selected category.
- Updated rows expose previous/current text in “What changed?”.
- Expanded change details survive filtering and page navigation during the current visit.
- The “Historical” toggle sits above the list, opposite the update time; its accessible name gives the archive's month. Month history is merged with recent commits and loaded only on request. Failed requests offer Retry.
- The generator embeds the available archive month before download. Filters reset through their own controls (the All chip, All categories, the search clear button); there is no separate clear-all button or result count.
- Search is debounced by 120 ms; normalized text, rendered link markup, sorted commits, and row collections are cached in memory.
- Facet counts and matching rows are computed together and reused during pagination. Unchanged category controls retain their DOM; off-screen resource layout is deferred by the browser.
- System fonts avoid external font requests. Search and filters scroll naturally with the page. Above 600px the search is a 150px field in the header, before the theme switcher; on phones it takes the header's second row. The phone category select has no visible label (its accessible name is "Filter by category").
- The HTML generator writes minified, content-hashed CSS/JS under `static/dist/`. Both Pages workflows include these assets. Rebuild after changing template/source assets using the Python environment where you installed the project dependencies:

  ```bash
  python -c "import json; from pathlib import Path; from fmhy_tracker import HTMLGenerator; HTMLGenerator().generate(json.loads(Path('fmhy_data.json').read_text(encoding='utf-8')))"
  ```

- The generated stylesheet has a 6.5 KiB gzip budget. The generator test checks the actual minified bundle from the source assets, so a source change cannot bypass the guard by leaving `index.html` stale.
- The generated application script has an 11 KiB gzip budget, checked the same way from the source assets.
- Pages publishes `deployment-revision.json` with the requested and deployed commit SHAs. Deployments fail before publication if their requested revision is no longer the default-branch tip.

Frontend regression checks (Node.js required): `node --test tests/frontend.test.cjs`.

Optional real-browser checks: `node tests/browser-check.cjs` with an existing Playwright installation available to Node. Set `CHROME_PATH` to use an installed Chromium/Chrome executable. The script routes local files through an isolated test origin, checks responsive layouts and keyboard interactions, and writes screenshots and timing measurements to `.cache/browser-check/`. It does not access or modify the deployed site.

Run with `--baseline` before committing to compare against `HEAD:index.html` and its generated assets. The benchmark reports the deduplicated row count in the current dataset and 20 warmed samples per operation after four warm-ups. Timings cover synchronous rendering and forced layout, exclude search debounce and network transfer, and are machine-dependent. Live network loading and physical-phone performance are not measured by this check.
