"""Command-line interface for FMHY Tracker."""

import argparse
import logging

from .config import config
from .tracker import FMHYTracker


def main():
    """Main entry point for the FMHY Tracker CLI."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Track changes in the FMHY repository")
    parser.add_argument(
        "--repo",
        default=config.repo,
        help=f"GitHub repository to monitor (default: {config.repo})",
    )
    parser.add_argument(
        "--folder",
        default=config.folder_path,
        help=f"Folder path to monitor for changes (default: {config.folder_path})",
    )
    parser.add_argument(
        "--output",
        default=config.output_file,
        help=f"Output JSON file (default: {config.output_file})",
    )
    parser.add_argument("--no-html", action="store_true", help="Skip HTML generation")
    parser.add_argument("--history", action="store_true", help="Show historical data")
    parser.add_argument(
        "--no-rss", action="store_true", help="Skip RSS feed generation"
    )
    parser.add_argument(
        "--generate-monthly",
        action="store_true",
        help="Generate monthly commits aggregation file",
    )
    parser.add_argument(
        "--backfill-monthly",
        action="store_true",
        help="Backfill monthly data with historical commits from the current month",
    )

    args = parser.parse_args()

    tracker = FMHYTracker(
        repo=args.repo, folder_path=args.folder, output_file=args.output
    )

    if args.history:
        tracker.show_history()
    elif args.generate_monthly:
        tracker.generate_monthly_data()
    elif args.backfill_monthly:
        tracker.backfill_monthly_data()
    else:
        tracker.run(
            generate_html=not args.no_html,
            generate_rss=not args.no_rss,
        )


if __name__ == "__main__":
    main()
