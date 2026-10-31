"""The merge queue ruleset (.github/rulesets/main-merge-queue.json) and the jobs it requires.

- Every required check is the check run of exactly one job, in a workflow
  that runs on every pull request and every merge group, unfiltered: a
  check nothing reports holds every pull request and every merge group
  until the queue's timeout.
- Every job that gates what merges is required. A job skipped because a
  job it needs failed reports as passing, so a failed `changes` or
  `boot-test-preflight` would otherwise let everything below it pass.
  The exempt jobs are listed with the reason each is not a gate.
- Checks are bound to GitHub Actions, so a commit status with the same name
  cannot satisfy them.
- The queue's timeout outlasts the slowest required job.
"""


import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
RULESET = json.loads((ROOT / ".github" / "rulesets" / "main-merge-queue.json").read_text(encoding="utf-8"))
RULES = {rule["type"]: rule.get("parameters") for rule in RULESET["rules"]}
GITHUB_ACTIONS_APP_ID = 15368

# Jobs of the gating workflows that are not required checks, and why.
EXEMPT = {
    ("build.yml", "kernel-cache"): "releases only; a cache, never a gate",
    ("build.yml", "kernel-cache-dev"): "releases only; a cache, never a gate",
    ("build.yml", "boot-test"): "a matrix; boot-test-result is its one result",
    ("build.yml", "release"): "pushes to main only",
    ("build.yml", "nightly-status"): "schedule only",
}


def triggers(wf: dict) -> dict:
    # PyYAML reads the bare `on` key as boolean True.
    return wf.get("on", wf.get(True))


def check_names(job_id: str, job: dict) -> list[str]:
    """The check run names GitHub gives a job: its name, or per matrix entry `id (values)`."""
    name = job.get("name", job_id)
    matrix = (job.get("strategy") or {}).get("matrix")
    if not matrix:
        return [name]
    assert set(matrix) - {"include"} and "include" not in matrix, f"{job_id}: expand this matrix shape here"
    (key,) = matrix
    return [f"{name} ({value})" for value in matrix[key]]


def gating_workflows() -> dict[str, dict]:
    found = {}
    for path in sorted(WORKFLOWS.glob("*.y*ml")):
        wf = yaml.safe_load(path.read_text(encoding="utf-8"))
        if "merge_group" in triggers(wf):
            found[path.name] = wf
    return found


def jobs_by_check() -> dict[str, tuple[str, str]]:
    found: dict[str, tuple[str, str]] = {}
    for name, wf in gating_workflows().items():
        for job_id, job in wf["jobs"].items():
            if (name, job_id) in EXEMPT:
                found[f"exempt:{name}:{job_id}"] = (name, job_id)
                continue
            for check in check_names(job_id, job):
                assert check not in found, f"two jobs report the check {check!r}"
                found[check] = (name, job_id)
    return found


REQUIRED = [c["context"] for c in RULES["required_status_checks"]["required_status_checks"]]


def test_ruleset_applies_to_the_default_branch() -> None:
    assert RULESET["target"] == "branch"
    assert RULESET["enforcement"] == "active"
    assert RULESET["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert RULESET["bypass_actors"] == [], "nobody merges around the queue"


def test_gating_workflows_run_on_every_pull_request_and_merge_group() -> None:
    workflows = gating_workflows()
    assert {"build.yml", "unit-tests.yml", "docs-checks.yml", "lint-actions.yml"} <= set(workflows)
    for name, wf in workflows.items():
        on = triggers(wf)
        assert "pull_request" in on, name
        for event in ("pull_request", "merge_group"):
            assert not (on[event] or {}).get("paths") and not (on[event] or {}).get("paths-ignore"), (name, event)
            assert not (on[event] or {}).get("branches"), (name, event)


@pytest.mark.parametrize("check", REQUIRED)
def test_every_required_check_is_one_gating_job(check: str) -> None:
    assert check in jobs_by_check(), f"no job reports {check!r} on pull requests and merge groups"


def test_every_gating_job_is_required_or_exempt() -> None:
    assert len(set(REQUIRED)) == len(REQUIRED)
    for check, (workflow, job_id) in jobs_by_check().items():
        if (workflow, job_id) in EXEMPT:
            assert check not in REQUIRED, f"{workflow}:{job_id} is exempt but required"
        else:
            assert check in REQUIRED, f"{workflow}:{job_id} ({check!r}) is neither required nor in EXEMPT"
    for workflow, job_id in EXEMPT:
        assert job_id in gating_workflows()[workflow]["jobs"], f"{workflow}:{job_id} is gone; drop it from EXEMPT"


def test_required_checks_come_from_github_actions() -> None:
    for check in RULES["required_status_checks"]["required_status_checks"]:
        assert check["integration_id"] == GITHUB_ACTIONS_APP_ID, check["context"]


def test_merge_queue_outlasts_the_slowest_required_job() -> None:
    queue = RULES["merge_queue"]
    assert queue["merge_method"] == "SQUASH"
    assert queue["grouping_strategy"] == "ALLGREEN"
    assert queue["min_entries_to_merge"] >= 1
    slowest = max(
        gating_workflows()[workflow]["jobs"][job_id]["timeout-minutes"]
        for workflow, job_id in (jobs_by_check()[c] for c in REQUIRED)
    )
    assert queue["check_response_timeout_minutes"] >= slowest
    assert queue["check_response_timeout_minutes"] <= 360, "GitHub's maximum"
