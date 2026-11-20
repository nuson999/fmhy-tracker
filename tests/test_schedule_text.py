"""User-facing schedule text must match the cron in monitor.yml.

The dashboard footer and README once said "every 12 hours" after the workflow
moved to every 6 hours; this test catches that drift.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _cron_interval_hours() -> int:
    workflow = (ROOT / ".github" / "workflows" / "monitor.yml").read_text(
        encoding="utf-8"
    )
    crons = re.findall(r'cron:\s*"([^"]+)"', workflow)
    assert len(crons) == 1, f"expected one cron schedule, found {crons}"
    hour_field = crons[0].split()[1]
    match = re.fullmatch(r"\*/(\d+)", hour_field)
    assert match, f"expected an '*/N' hour field, got {hour_field!r}"
    return int(match.group(1))


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_dashboard_footer_matches_cron():
    hours = _cron_interval_hours()
    for name in ("templates/index.html", "index.html"):
        html = _normalize((ROOT / name).read_text(encoding="utf-8"))
        assert f"Updates every {hours} hours" in html, name


def test_readme_matches_cron():
    hours = _cron_interval_hours()
    readme = _normalize((ROOT / "README.md").read_text(encoding="utf-8"))
    assert f"updated every {hours} hours" in readme
    assert f"runs every {hours} hours" in readme
