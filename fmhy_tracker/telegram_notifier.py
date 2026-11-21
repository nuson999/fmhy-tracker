"""Telegram notifications for starred FMHY link changes.

Secrets rule: the bot token and chat ID come only from the environment
(`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, GitHub Actions secrets in CI). Never
hard-code them, log them, or let an exception message carry the request URL,
which contains the token. Without both values the notifier skips quietly.
"""

from __future__ import annotations

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


def collect_starred_link_changes(data: dict[str, Any]) -> list[dict[str, str]]:
    """New and removed starred links from this run's (non-historical) commits."""
    changes: list[dict[str, str]] = []
    for commit in data.get("commits", []):
        if commit.get("isHistorical"):
            continue
        for key, change_type in (("added", "new"), ("removed", "removed")):
            for item in commit.get(key, []):
                link = item.get("link", "")
                if item.get("type") == change_type and any(
                    star in link for star in STAR_TOKENS
                ):
                    changes.append(
                        {
                            "change_type": change_type,
                            "source": item.get("source", "unknown"),
                            "link": link,
                        }
                    )
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
    lines = [f"FMHY starred link changes ({len(changes)})", ""]
    for change_type, heading in (
        ("new", "New starred links"),
        ("removed", "Removed starred links"),
    ):
        items = [item for item in changes if item["change_type"] == change_type]
        if not items:
            continue
        lines.append(f"{heading} ({len(items)})")
        for index, item in enumerate(items, start=1):
            parsed = parse_markdown_link(item["link"])
            lines.append(f"{index}. [{item['source']}] {parsed['name']}")
            if parsed["url"]:
                lines.append(parsed["url"])
            if parsed["description"]:
                lines.append(parsed["description"])
            lines.append("")
        lines.append("")
    lines.append(config.rss_link)
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


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    args = sys.argv[1:] if argv is None else argv
    try:
        notify_starred_links(args[0] if args else config.output_file)
    except TelegramError as exc:
        logger.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
