"""Publishing failures must stop the monitor before it dispatches a deploy."""

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_monitor_stops_on_git_publish_failure_and_checks_dispatch_response():
    workflow = (ROOT / ".github" / "workflows" / "monitor.yml").read_text(
        encoding="utf-8"
    )

    commit_step = workflow.index("- name: Commit and push last commit SHA")
    dispatch_step = workflow.index("- name: Trigger GitHub Pages deployment")
    publish_script = workflow[commit_step:dispatch_step]
    dispatch_script = workflow[dispatch_step:]

    assert "if ! git diff --staged --quiet; then" in publish_script
    assert 'git commit -m "Update tracker data and webpage"' in publish_script
    assert "git push" in publish_script
    assert "git push --force" not in publish_script
    assert 'echo "sha=$(git rev-parse HEAD)" >> "$GITHUB_OUTPUT"' in publish_script
    assert "|| echo" not in publish_script
    assert "curl --fail-with-body" in dispatch_script
    assert '"sha": "${{ steps.publish.outputs.sha }}"' in dispatch_script


def test_monitor_runs_queue_and_start_from_the_branch_tip():
    """A push run and a manual run once overlapped; the second push was rejected."""
    workflow = (ROOT / ".github" / "workflows" / "monitor.yml").read_text(
        encoding="utf-8"
    )
    monitor = workflow[workflow.index("  monitor:") :]
    concurrency = monitor[monitor.index("concurrency:") : monitor.index("steps:")]
    assert "group: monitor-publish-" in concurrency
    assert "cancel-in-progress: false" in concurrency
    checkout = monitor[
        monitor.index("uses: actions/checkout") : monitor.index("- name: Set up")
    ]
    assert "ref: ${{ github.ref_name }}" in checkout


def test_pages_checks_out_records_and_rejects_stale_requested_revision():
    workflow = (ROOT / ".github" / "workflows" / "static.yml").read_text(
        encoding="utf-8"
    )

    assert "ref: ${{ github.event.client_payload.sha || github.sha }}" in workflow
    assert 'DEPLOYED_SHA="$(git rev-parse HEAD)"' in workflow
    assert '"$EXPECTED_SHA" != "$DEPLOYED_SHA"' in workflow
    assert "public/deployment-revision.json" in workflow
    assert '"$EXPECTED_SHA" != "$CURRENT_SHA"' in workflow
    assert workflow.index("- name: Confirm revision is current") < workflow.index(
        "- name: Deploy to GitHub Pages"
    )


def test_overlapping_stale_publish_cannot_move_remote_sha_backward(tmp_path):
    remote = tmp_path / "remote.git"
    first = tmp_path / "first"
    second = tmp_path / "second"

    def git(*args, cwd=None, check=True):
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )

    git("init", "--bare", "--initial-branch=main", str(remote))
    git("clone", remote.as_uri(), str(first))
    git("-C", str(first), "config", "user.name", "Workflow Test")
    git("-C", str(first), "config", "user.email", "workflow-test@example.invalid")
    (first / "last_commit_sha.txt").write_text("base-sha\n", encoding="utf-8")
    git("-C", str(first), "add", "last_commit_sha.txt")
    git("-C", str(first), "commit", "-m", "base")
    git("-C", str(first), "push", "-u", "origin", "main")
    git("clone", remote.as_uri(), str(second))

    for checkout, sha in ((first, "newer-sha"), (second, "stale-sha")):
        git("-C", str(checkout), "config", "user.name", "Workflow Test")
        git(
            "-C", str(checkout), "config", "user.email", "workflow-test@example.invalid"
        )
        (checkout / "last_commit_sha.txt").write_text(f"{sha}\n", encoding="utf-8")
        git("-C", str(checkout), "add", "last_commit_sha.txt")
        git("-C", str(checkout), "commit", "-m", sha)

    git("-C", str(first), "push", "origin", "main")
    rejected = git("-C", str(second), "push", "origin", "main", check=False)

    assert rejected.returncode != 0
    remote_sha = git("--git-dir", str(remote), "show", "main:last_commit_sha.txt")
    assert remote_sha.stdout.strip() == "newer-sha"
