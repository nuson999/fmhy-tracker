"""Configuration environment parsing tests."""

import pytest

from fmhy_tracker.config import Config


@pytest.mark.parametrize(
    ("name", "minimum", "expected_attribute", "default"),
    [
        (
            "FMHY_GITHUB_TIMEOUT_SECONDS",
            1,
            "github_timeout_seconds",
            Config.DEFAULT_GITHUB_TIMEOUT_SECONDS,
        ),
        (
            "FMHY_GITHUB_RETRIES",
            0,
            "github_retries",
            Config.DEFAULT_GITHUB_RETRIES,
        ),
        ("FMHY_MIN_COMMITS", 0, "min_commits", Config.DEFAULT_MIN_COMMITS),
        (
            "FMHY_MAX_HISTORY",
            0,
            "max_history_files",
            Config.DEFAULT_MAX_HISTORY_FILES,
        ),
    ],
)
def test_integer_settings_reject_values_below_minimum(
    monkeypatch, caplog, name, minimum, expected_attribute, default
):
    monkeypatch.setenv(name, str(minimum - 1))

    settings = Config()

    assert getattr(settings, expected_attribute) == default
    assert name in caplog.text
    assert f"minimum is {minimum}" in caplog.text


@pytest.mark.parametrize(
    ("name", "expected_attribute"),
    [
        ("FMHY_GITHUB_RETRIES", "github_retries"),
        ("FMHY_MIN_COMMITS", "min_commits"),
        ("FMHY_MAX_HISTORY", "max_history_files"),
    ],
)
def test_zero_is_valid_for_nonnegative_integer_settings(
    monkeypatch, name, expected_attribute
):
    monkeypatch.setenv(name, "0")

    settings = Config()

    assert getattr(settings, expected_attribute) == 0


def test_non_integer_setting_uses_default_with_warning(monkeypatch, caplog):
    monkeypatch.setenv("FMHY_GITHUB_RETRIES", "many")

    settings = Config()

    assert settings.github_retries == Config.DEFAULT_GITHUB_RETRIES
    assert "Invalid FMHY_GITHUB_RETRIES='many'" in caplog.text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("", ""),
        ("https://t.me/fmhy_changes", "https://t.me/fmhy_changes"),
        ("http://t.me/fmhy_changes", ""),
        ("https://t.me/x", ""),
        ('https://t.me/fmhy"><script>', ""),
        ("https://evil.example/fmhy_changes", ""),
    ],
)
def test_telegram_channel_url_accepts_only_public_t_me_links(
    monkeypatch, raw, expected
):
    monkeypatch.setenv("FMHY_TELEGRAM_URL", raw)
    assert Config().telegram_channel_url == expected
