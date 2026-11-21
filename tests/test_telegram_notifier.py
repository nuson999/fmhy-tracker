"""Telegram notifier: starred-link selection, formatting, and token safety."""

import json
from pathlib import Path

import pytest
import requests

from fmhy_tracker import telegram_notifier as tn

ROOT = Path(__file__).resolve().parent.parent
FAKE_TOKEN = "123456:TEST-not-a-real-token"

# Real lines from data/history.
EMAILNATOR = (
    "* ⭐ **[Emailnator](https://emailnator.com/)** - "
    "Gmail / Forever / 1 Day / 6 Domains"
)
WINDHAWK = (
    "* ⭐ **[Windhawk](https://windhawk.net/)**, [MajorGeeks Windows Tweaks]"
    "(https://www.majorgeeks.com/files/details/majorgeeks_registry_tweaks.html) "
    "or [Winaero](https://winaero.com/) / [2](https://winaerotweaker.com/) - "
    "System Tweaking Tools"
)


def _data():
    return {
        "commits": [
            {
                "isHistorical": False,
                "added": [
                    {"link": EMAILNATOR, "source": "internet-tools", "type": "new"},
                    {
                        "link": "* [Plain](https://p.example)",
                        "source": "x",
                        "type": "new",
                    },
                    {"link": WINDHAWK, "source": "system-tools", "type": "updated"},
                ],
                "removed": [
                    {"link": WINDHAWK, "source": "system-tools", "type": "removed"},
                ],
            },
            {
                "isHistorical": True,
                "added": [{"link": EMAILNATOR, "source": "old", "type": "new"}],
            },
        ]
    }


class FakeResponse:
    def __init__(self, status=200, body=None):
        self.status_code = status
        self._body = body if body is not None else {"ok": True}

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.calls = []
        self.response = response or FakeResponse()
        self.exc = exc

    def post(self, url, data, timeout):
        self.calls.append((url, data))
        if self.exc:
            raise self.exc
        return self.response


def test_collects_only_this_runs_new_and_removed_starred_links():
    changes = tn.collect_starred_link_changes(_data())
    assert [(c["change_type"], c["source"]) for c in changes] == [
        ("new", "internet-tools"),
        ("removed", "system-tools"),
    ]


def test_parse_real_link_keeps_name_url_description():
    parsed = tn.parse_markdown_link(EMAILNATOR)
    assert parsed == {
        "name": "Emailnator",
        "url": "https://emailnator.com/",
        "description": "Gmail | Forever | 1 Day | 6 Domains",
    }


def test_message_groups_changes():
    message = tn.format_notification_message(tn.collect_starred_link_changes(_data()))
    assert "New starred links (1)" in message
    assert "Removed starred links (1)" in message
    assert "https://windhawk.net/" in message


def test_split_message_respects_limit():
    chunks = tn.split_message("\n".join(["x" * 50] * 10), limit=120)
    assert all(len(c) <= 120 for c in chunks)
    assert "".join(chunks).replace("\n", "") == "x" * 500


def test_skips_without_secrets(tmp_path):
    data_file = tmp_path / "d.json"
    data_file.write_text(json.dumps(_data()), encoding="utf-8")
    session = FakeSession()
    assert not tn.notify_starred_links(str(data_file), "", "1", session)
    assert not tn.notify_starred_links(str(data_file), FAKE_TOKEN, "", session)
    assert session.calls == []


def test_sends_one_message_when_starred_changes_exist(tmp_path):
    data_file = tmp_path / "d.json"
    data_file.write_text(json.dumps(_data()), encoding="utf-8")
    session = FakeSession()
    assert tn.notify_starred_links(str(data_file), FAKE_TOKEN, "42", session)
    assert len(session.calls) == 1
    assert session.calls[0][1]["chat_id"] == "42"


@pytest.mark.parametrize(
    "session",
    [
        FakeSession(
            exc=requests.ConnectionError(
                f"Max retries exceeded with url: /bot{FAKE_TOKEN}/sendMessage"
            )
        ),
        FakeSession(
            response=FakeResponse(
                401, {"ok": False, "description": f"Unauthorized {FAKE_TOKEN}"}
            )
        ),
    ],
)
def test_errors_never_contain_the_token(session):
    with pytest.raises(tn.TelegramError) as info:
        tn.send_message("hi", FAKE_TOKEN, "42", session)
    assert FAKE_TOKEN not in str(info.value)
    assert info.value.__cause__ is None
    assert info.value.__context__ is None or info.value.__suppress_context__


def test_no_telegram_secret_is_committed():
    """Telegram secrets live in Actions secrets, never in tracked files."""
    token_pattern = __import__("re").compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")
    for path in ROOT.glob("**/*"):
        if not path.is_file() or path.suffix not in {".py", ".yml", ".md", ".toml"}:
            continue
        if any(p in {"venv", ".venv", ".git", "node_modules"} for p in path.parts):
            continue
        assert not token_pattern.search(
            path.read_text(encoding="utf-8", errors="ignore")
        ), path


def test_workflow_notifies_after_publish_from_secrets_without_failing_run():
    workflow = (ROOT / ".github" / "workflows" / "monitor.yml").read_text(
        encoding="utf-8"
    )
    step = workflow.index("- name: Send Telegram notification")
    assert workflow.index("- name: Commit and push last commit SHA") < step
    notify = workflow[step:]
    assert "continue-on-error: true" in notify
    assert "TELEGRAM_BOT_TOKEN: ${{ secrets.TELEGRAM_BOT_TOKEN }}" in notify
    assert "TELEGRAM_CHAT_ID: ${{ secrets.TELEGRAM_CHAT_ID }}" in notify


# Real line from data/history; FMHY also marks top picks with 🌟.
KOTOPLAY = (
    "* 🌟 **[KotoPlay](https://kotoplay.to/)** or [Anisuge](https://animesuge.cz/) "
    "- Sub / Dub / Auto-Next"
)


def test_glowing_star_links_count_as_starred():
    data = {
        "commits": [
            {
                "isHistorical": False,
                "added": [{"link": KOTOPLAY, "source": "video", "type": "new"}],
            }
        ]
    }
    changes = tn.collect_starred_link_changes(data)
    assert [c["source"] for c in changes] == ["video"]
    parsed = tn.parse_markdown_link(KOTOPLAY)
    assert parsed["name"] == "KotoPlay"
    assert parsed["url"] == "https://kotoplay.to/"
