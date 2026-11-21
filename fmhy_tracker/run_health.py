"""Summarize recent GitHub Actions health for the monitor and Pages deploy."""

import argparse
import json
import subprocess
import sys


WORKFLOWS = {
    "monitor": "monitor.yml",
    "deploy": "static.yml",
}
RUN_FIELDS = "databaseId,workflowName,status,conclusion,createdAt,url"
FAILED_JOB_CONCLUSIONS = {
    "action_required",
    "cancelled",
    "failure",
    "startup_failure",
    "timed_out",
}


def _gh_json(*args):
    result = subprocess.run(["gh", *args], capture_output=True, check=False, text=True)
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(detail or "GitHub CLI command failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("GitHub CLI returned invalid JSON") from exc


def summarize_runs(runs, jobs_by_id):
    """Count completed runs that started and separate active/unstarted runs."""
    summary = {
        "started": 0,
        "succeeded": 0,
        "failed": [],
        "not_started": 0,
        "active": 0,
    }
    for run in runs:
        if run.get("status") != "completed":
            summary["active"] += 1
            continue

        jobs = jobs_by_id.get(str(run.get("databaseId")), [])
        started = any(job.get("startedAt") for job in jobs)
        if not started:
            summary["not_started"] += 1
            continue

        summary["started"] += 1
        if run.get("conclusion") == "success":
            summary["succeeded"] += 1
        else:
            summary["failed"].append(
                {
                    "conclusion": run.get("conclusion") or "unknown",
                    "url": run.get("url", ""),
                    "jobs": [
                        {
                            "name": job.get("name") or "unnamed job",
                            "conclusion": job.get("conclusion"),
                        }
                        for job in jobs
                        if job.get("conclusion") in FAILED_JOB_CONCLUSIONS
                    ],
                }
            )
    return summary


def collect_workflow(path, limit):
    runs = _gh_json(
        "run",
        "list",
        "--workflow",
        path,
        "--limit",
        str(limit),
        "--json",
        RUN_FIELDS,
    )
    if not isinstance(runs, list):
        raise RuntimeError(f"Expected a run list for {path}")

    jobs_by_id = {}
    for run in runs:
        if run.get("status") == "completed":
            run_id = run.get("databaseId")
            if run_id is None:
                raise RuntimeError(f"Run in {path} has no databaseId")
            jobs = _gh_json("run", "view", str(run_id), "--json", "jobs")
            if not isinstance(jobs, dict) or not isinstance(jobs.get("jobs"), list):
                raise RuntimeError(f"Expected job details for run {run_id}")
            jobs_by_id[str(run_id)] = jobs["jobs"]
    return summarize_runs(runs, jobs_by_id)


def format_summary(name, summary):
    started = summary["started"]
    success = summary["succeeded"]
    rate = f"{success / started:.0%}" if started else "n/a"
    lines = [
        f"{name}: {success}/{started} started runs succeeded ({rate}); "
        f"{len(summary['failed'])} failed; {summary['active']} active; "
        f"{summary['not_started']} excluded (no job started, including billing blocks)"
    ]
    for failure in summary["failed"]:
        jobs = ", ".join(
            f"{job['name']} ({job['conclusion']})" for job in failure.get("jobs", [])
        )
        detail = f"; jobs: {jobs}" if jobs else ""
        lines.append(f"  {failure['conclusion']}{detail}: {failure['url']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Summarize recent monitor and Pages workflow runs"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="completed and active runs to inspect per workflow (1-100)",
    )
    args = parser.parse_args(argv)
    if not 1 <= args.limit <= 100:
        parser.error("--limit must be between 1 and 100")

    try:
        for name, path in WORKFLOWS.items():
            print(format_summary(name, collect_workflow(path, args.limit)))
    except (OSError, RuntimeError) as exc:
        print(f"fmhy-run-health: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
