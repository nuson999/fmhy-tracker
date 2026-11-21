from unittest.mock import call, patch

import pytest

from fmhy_tracker.run_health import (
    RUN_FIELDS,
    collect_workflow,
    format_summary,
    main,
    summarize_runs,
)


def test_summarize_runs_excludes_runs_with_no_started_jobs():
    runs = [
        {"databaseId": 1, "status": "completed", "conclusion": "success"},
        {"databaseId": 2, "status": "completed", "conclusion": "failure"},
        {"databaseId": 3, "status": "completed", "conclusion": "failure"},
        {"databaseId": 4, "status": "in_progress", "conclusion": None},
    ]
    jobs = {
        "1": [{"startedAt": "2026-11-20T00:00:00Z"}],
        "2": [
            {
                "name": "test",
                "startedAt": "2026-11-20T01:00:00Z",
                "conclusion": "failure",
            },
            {"name": "deploy", "conclusion": "skipped"},
        ],
        "3": [{"startedAt": None, "conclusion": "skipped"}],
    }

    summary = summarize_runs(runs, jobs)

    assert summary == {
        "started": 2,
        "succeeded": 1,
        "failed": [
            {
                "conclusion": "failure",
                "url": "",
                "jobs": [{"name": "test", "conclusion": "failure"}],
            }
        ],
        "not_started": 1,
        "active": 1,
    }


def test_format_summary_names_billing_blocks_as_excluded_not_failures():
    summary = {
        "started": 4,
        "succeeded": 3,
        "failed": [
            {
                "conclusion": "failure",
                "url": "https://example.test/run/2",
                "jobs": [
                    {"name": "test", "conclusion": "failure"},
                    {"name": "deploy", "conclusion": "timed_out"},
                ],
            }
        ],
        "not_started": 1,
        "active": 0,
    }

    output = format_summary("monitor", summary)

    assert "3/4 started runs succeeded (75%)" in output
    assert "1 excluded (no job started, including billing blocks)" in output
    assert (
        "failure; jobs: test (failure), deploy (timed_out): https://example.test/run/2"
    ) in output


def test_summarize_runs_reports_cancelled_jobs_but_omits_skipped_jobs():
    runs = [
        {
            "databaseId": 5,
            "status": "completed",
            "conclusion": "cancelled",
            "url": "https://example.test/run/5",
        }
    ]
    jobs = {
        "5": [
            {
                "name": "build",
                "startedAt": "2026-11-20T02:00:00Z",
                "conclusion": "cancelled",
            },
            {"name": "deploy", "conclusion": "skipped"},
        ]
    }

    summary = summarize_runs(runs, jobs)

    assert summary["failed"] == [
        {
            "conclusion": "cancelled",
            "url": "https://example.test/run/5",
            "jobs": [{"name": "build", "conclusion": "cancelled"}],
        }
    ]


@pytest.mark.parametrize("conclusion", ["action_required", "startup_failure"])
def test_summarize_runs_reports_less_common_actionable_job_conclusions(conclusion):
    runs = [
        {"databaseId": 6, "status": "completed", "conclusion": "failure"},
    ]
    jobs = {
        "6": [
            {
                "name": "release",
                "startedAt": "2026-11-20T03:00:00Z",
                "conclusion": conclusion,
            }
        ]
    }

    summary = summarize_runs(runs, jobs)

    assert summary["failed"][0]["jobs"] == [
        {"name": "release", "conclusion": conclusion}
    ]


def test_success_rate_is_not_applicable_without_started_runs():
    summary = {
        "started": 0,
        "succeeded": 0,
        "failed": [],
        "not_started": 2,
        "active": 0,
    }

    assert "0/0 started runs succeeded (n/a)" in format_summary("deploy", summary)


@patch("fmhy_tracker.run_health._gh_json")
def test_collect_workflow_uses_cli_filename_and_started_job_details(mock_gh_json):
    mock_gh_json.side_effect = [
        [
            {
                "databaseId": 8,
                "status": "completed",
                "conclusion": "success",
            },
            {
                "databaseId": 9,
                "status": "in_progress",
                "conclusion": None,
            },
        ],
        {"jobs": [{"startedAt": "2026-11-20T00:00:00Z"}]},
    ]

    summary = collect_workflow("monitor.yml", 5)

    assert summary["started"] == 1
    assert summary["succeeded"] == 1
    assert summary["active"] == 1
    assert mock_gh_json.call_args_list == [
        call(
            "run",
            "list",
            "--workflow",
            "monitor.yml",
            "--limit",
            "5",
            "--json",
            RUN_FIELDS,
        ),
        call("run", "view", "8", "--json", "jobs"),
    ]


@patch("fmhy_tracker.run_health.collect_workflow")
def test_main_reports_github_cli_errors_with_nonzero_exit(mock_collect, capsys):
    mock_collect.side_effect = RuntimeError("authentication required")

    result = main(["--limit", "5"])

    captured = capsys.readouterr()
    assert result == 1
    assert captured.out == ""
    assert "fmhy-run-health: authentication required" in captured.err
