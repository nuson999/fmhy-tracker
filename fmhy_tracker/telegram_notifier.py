"""Telegram notifications for starred FMHY link changes.

Secrets rule: the bot token and chat ID come only from the environment
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, GitHub Actions secrets in CI). Never
hard-code them, log them, or let an exception message carry the request URL,
which contains the token. Without both values the notifier skips quietly.

Messages never include the dashboard URL (owner's choice).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from typing import Any

import requests

from .config import config

logger = logging.getLogger(__name__)

# FMHY marks top picks with either star.
STAR_TOKENS = ("⭐", "🌟")
TELEGRAM_API_BASE = "https://api.telegram.org"
TELEGRAM_MESSAGE_LIMIT = 4096
TELEGRAM_TIMEOUT_SECONDS = 30


class TelegramError(RuntimeError):
    """A Telegram request failed; the message never contains the bot token."""


def _redact(text: str, token: str) -> str:
    return str(text).replace(token, "<redacted>") if token else str(text)


def split_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT) -> list[str]:
    """Split a message into Telegram-sized chunks, preferring line breaks."""
    remaining = str(text).strip()
    if not remaining:
        raise ValueError("Message must not be empty.")

    chunks: list[str] = []
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = remaining.rfind(" ", 0, limit)
        if split_at <= 0:
            split_at = limit
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    if remaining:
        chunks.append(remaining)
    return [chunk for chunk in chunks if chunk]


def send_message(message: str, token: str, chat_id: str, session=None) -> None:
    """Send a message to one chat, raising TelegramError with a redacted reason."""
    http = session or requests
    url = f"{TELEGRAM_API_BASE}/bot{token}/sendMessage"
    for chunk in split_message(message):
        try:
            response = http.post(
                url,
                data={
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": "true",
                },
                timeout=TELEGRAM_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            # `from None`: the original exception text can include the URL.
            raise TelegramError(
                _redact(f"Telegram request failed: {type(exc).__name__}", token)
            ) from None

        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200 or not body.get("ok"):
            description = body.get("description") or "no description"
            raise TelegramError(
                _redact(
                    f"Telegram API error (HTTP {response.status_code}): {description}",
                    token,
                )
            )


def load_tracker_data(data_file: str = "fmhy_data.json") -> dict[str, Any]:
    with open(data_file, "r", encoding="utf-8") as file:
        return json.load(file)


def is_starred(link: str) -> bool:
    return any(star in link for star in STAR_TOKENS)


def collect_starred_link_changes(data: dict[str, Any]) -> list[dict[str, str]]:
    """New, updated and removed starred links from this run's commits.

    Historical commits (re-shown only to fill the dashboard) are skipped. An
    update counts when the line is starred before or after the change, so links
    that gain or lose their star are reported too.
    """
    changes: list[dict[str, str]] = []
    for commit in data.get("commits", []):
        if commit.get("isHistorical"):
            continue
        for key in ("added", "removed"):
            for item in commit.get(key, []):
                change_type = item.get("type")
                link = item.get("link", "")
                previous = item.get("relatedLink", "")
                expected = ("new", "updated") if key == "added" else ("removed",)
                if change_type not in expected:
                    continue
                if not (is_starred(link) or is_starred(previous)):
                    continue
                change = {
                    "change_type": change_type,
                    "source": item.get("source", "unknown"),
                    "link": link,
                }
                if change_type == "updated":
                    change["previous_link"] = previous
                changes.append(change)
    return changes


def parse_markdown_link(markdown_link: str) -> dict[str, str]:
    """Extract the display name, main URL and description from one FMHY line."""
    text = re.sub(r"^\*\s*", "", markdown_link.strip())
    text = re.sub(rf"^(?:{'|'.join(STAR_TOKENS)})\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)

    match = re.search(r"\[([^\]]+)\]\(([^)]+)\)", text)
    if not match:
        return {"name": text, "url": "", "description": ""}

    description = text[match.end() :].strip()
    if description.startswith("-"):
        description = description[1:].strip()
    description = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", description)
    description = " ".join(description.split()).replace(" /", " |")
    return {
        "name": match.group(1).strip(),
        "url": match.group(2).strip(),
        "description": description,
    }


def format_notification_message(changes: list[dict[str, str]]) -> str:
    sections = (
        ("new", "New", "New starred links"),
        ("updated", "Updated", "Updated starred links"),
        ("removed", "Removed", "Removed starred links"),
    )
    # Summary first so the counts show in the chat preview.
    counts = " · ".join(
        f"{label} {sum(1 for c in changes if c['change_type'] == change_type)}"
        for change_type, label, _ in sections
    )
    lines = [f"FMHY starred link changes ({len(changes)})", counts, ""]
    for change_type, _, heading in sections:
        items = [item for item in changes if item["change_type"] == change_type]
        if not items:
            continue
        lines.extend([f"{heading} ({len(items)})", ""])
        for index, item in enumerate(items, start=1):
            parsed = parse_markdown_link(item["link"])
            title = f"{index}. [{item['source']}] {parsed['name']}"
            previous = item.get("previous_link")
            if previous is not None:
                if not is_starred(previous):
                    title += " (now starred)"
                elif not is_starred(item["link"]):
                    title += " (no longer starred)"
            lines.append(title)
            if parsed["url"]:
                lines.append(parsed["url"])
            if parsed["description"]:
                lines.append(parsed["description"])
            if previous:
                old_url = parse_markdown_link(previous)["url"]
                if old_url and old_url != parsed["url"]:
                    lines.append(f"Was: {old_url}")
            lines.append("")
        lines.append("")
    return "\n".join(lines).strip()


def notify_starred_links(
    data_file: str = "fmhy_data.json",
    token: str | None = None,
    chat_id: str | None = None,
    session=None,
) -> bool:
    """Send one notification for this run's starred link changes.

    Returns True when a message was sent. Skips (False) when Telegram is not
    configured or nothing starred changed.
    """
    token = token if token is not None else config.telegram_bot_token
    chat_id = chat_id if chat_id is not None else config.telegram_chat_id
    if not token or not chat_id:
        logger.info(
            "TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID not set; skipping Telegram."
        )
        return False

    changes = collect_starred_link_changes(load_tracker_data(data_file))
    if not changes:
        logger.info("No starred link changes; skipping Telegram notification.")
        return False

    send_message(format_notification_message(changes), token, chat_id, session)
    logger.info("Sent Telegram notification for %s starred change(s).", len(changes))
    return True


TEST_MESSAGE = (
    "FMHY Tracker test message: Telegram notifications are set up. "
    "New, updated and removed starred (⭐/🌟) links will be posted here."
)


def send_test_message(
    token: str | None = None, chat_id: str | None = None, session=None
) -> None:
    """Send a fixed test message; missing secrets are an error, not a skip."""
    token = token if token is not None else config.telegram_bot_token
    chat_id = chat_id if chat_id is not None else config.telegram_chat_id
    if not token or not chat_id:
        raise TelegramError(
            "Test message not sent: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set."
        )
    send_message(TEST_MESSAGE, token, chat_id, session)
    logger.info("Sent Telegram test message.")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("data_file", nargs="?", default=config.output_file)
    parser.add_argument(
        "--test", action="store_true", help="send a test message and exit"
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.test:
            send_test_message()
        else:
            notify_starred_links(args.data_file)
    except TelegramError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
