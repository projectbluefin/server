"""Contracts of the lightweight CI workflows and the Renovate pins they use.

- unit-tests, docs-checks and lint-actions report on every pull request and
  push to main, so each can be a required check.
- The unit workflow runs the tests of every Go module in the repository; the
  image build runs them too, and a failure found only there fails a release.
- pip installs come from the exactly pinned .github/requirements-ci.txt.
- renovate.json's regex managers match the pins as written today; a manager
  that silently matches nothing reports no updates rather than an error.
- The nightly build and the trackers each open, update and close one
  tracking issue through .github/scripts/tracking-issue.sh.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
REQUIREMENTS = ".github/requirements-ci.txt"
RENOVATE = json.loads((ROOT / "renovate.json").read_text(encoding="utf-8"))


def workflow(name: str) -> dict:
    return yaml.safe_load((WORKFLOWS / name).read_text(encoding="utf-8"))


def triggers(wf: dict) -> dict:
    # PyYAML reads the bare `on` key as boolean True.
    return wf.get("on", wf.get(True))


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True).stdout
    return [line for line in out.splitlines() if line]


def all_workflows() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.y*ml"))


@pytest.mark.parametrize("name", ["unit-tests.yml", "docs-checks.yml", "lint-actions.yml"])
def test_check_workflows_run_on_every_pull_request_and_main_push(name: str) -> None:
    wf = workflow(name)
    on = triggers(wf)
    assert set(on) == {"pull_request", "push"}, name
    assert not on["pull_request"], f"{name}: a filtered pull_request trigger cannot be a required check"
    assert on["push"] == {"branches": ["main"]}, name
    for job_name, job in wf["jobs"].items():
        assert isinstance(job.get("timeout-minutes"), int), f"{name}:{job_name} has no timeout-minutes"



def go_modules() -> list[str]:
    return sorted(
        str(Path(p).parent)
        for p in tracked_files()
        if Path(p).name == "go.mod" and "vendor" not in Path(p).parts
    )


def test_unit_workflow_tests_every_go_module() -> None:
    modules = go_modules()
    assert modules, "no go.mod found; drop the go job or fix the search"
    job = workflow("unit-tests.yml")["jobs"]["go"]
    assert sorted(job["strategy"]["matrix"]["module"]) == modules
    assert job["defaults"]["run"]["working-directory"] == "${{ matrix.module }}"

    setup = [s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/setup-go@")]
    assert len(setup) == 1
    assert re.fullmatch(r"actions/setup-go@[0-9a-f]{40}", setup[0]["uses"])
    assert setup[0]["with"]["go-version-file"] == "${{ matrix.module }}/go.mod"

    runs = "\n".join(s.get("run", "") for s in job["steps"])
    for command in ("gofmt -l", "go vet ./...", "go test -race ./..."):
        assert command in runs, command



def test_pip_installs_only_the_pinned_requirements() -> None:
    installs = []
    for path in all_workflows():
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.search(r"\bpip3? install\b", line):
                installs.append((path.name, line.strip()))
    assert installs, "no pip install found; drop this test or the requirements file"
    for name, line in installs:
        assert line == f"pip install -r {REQUIREMENTS}" or line == f"run: pip install -r {REQUIREMENTS}", (name, line)


def test_ci_requirements_are_exact_pins() -> None:
    lines = [
        line.strip()
        for line in (ROOT / REQUIREMENTS).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert {"pytest", "pyyaml"} <= {line.split("==")[0].lower() for line in lines}
    for line in lines:
        assert re.fullmatch(r"[A-Za-z0-9._-]+==[0-9][0-9A-Za-z.+!-]*", line), line



def js_regex(pattern: str) -> re.Pattern[str]:
    """A Renovate (JavaScript) regex as a Python one: (?<name> -> (?P<name>."""
    if pattern.startswith("/") and pattern.endswith("/"):
        pattern = pattern[1:-1]
    return re.compile(re.sub(r"\(\?<(?=[A-Za-z])", "(?P<", pattern))


def regex_manager(dep_name: str) -> dict:
    managers = [m for m in RENOVATE["customManagers"] if m.get("depNameTemplate") == dep_name]
    assert len(managers) == 1, dep_name
    return managers[0]


def managed_files(manager: dict) -> list[str]:
    patterns = [js_regex(p) for p in manager["managerFilePatterns"]]
    return [p for p in tracked_files() if any(r.search(p) for r in patterns)]


def matches(manager: dict) -> list[tuple[str, re.Match[str]]]:
    found = []
    for path in managed_files(manager):
        text = (ROOT / path).read_text(encoding="utf-8")
        for pattern in manager["matchStrings"]:
            found += [(path, m) for m in js_regex(pattern).finditer(text)]
    return found


def test_renovate_tracks_every_just_pin() -> None:
    manager = regex_manager("just")
    assert manager["datasourceTemplate"] == "github-releases"
    assert manager["packageNameTemplate"] == "casey/just"

    pins = []
    for path in tracked_files():
        if path.startswith("docs/"):
            continue
        text = (ROOT / path).read_text(encoding="utf-8", errors="replace")
        pins += [(path, m.group(1)) for m in re.finditer(r"\bjust@([0-9][^\s'\"]*)", text)]
    found = [(path, m.group("currentValue")) for path, m in matches(manager)]

    assert len({p for p, _ in found}) >= 4, found
    assert sorted(found) == sorted(pins), "a just@ pin the Renovate manager does not match"
    assert len({v for _, v in found}) == 1, f"CI runs more than one just version: {found}"


def test_renovate_tracks_the_bst2_image_tag() -> None:
    manager = regex_manager("bst2")
    assert manager["datasourceTemplate"] == "git-refs"
    assert manager["currentValueTemplate"] == "master"
    assert manager["packageNameTemplate"].endswith("/freedesktop-sdk-docker-images.git")

    justfile = (ROOT / "Justfile").read_text(encoding="utf-8")
    image = re.search(r'^export bst2_image := env\("BST2_IMAGE", "([^"]+)"\)$', justfile, re.MULTILINE)
    assert image, "bst2_image moved; update the Renovate manager and this test"
    assert "@sha256:" not in image.group(1)

    found = matches(manager)
    assert [p for p, _ in found] == ["Justfile"]
    assert image.group(1).endswith(":" + found[0][1].group("currentDigest"))


def test_renovate_tracks_the_ci_requirements() -> None:
    # Renovate's default pip_requirements file pattern.
    default = re.compile(r"(^|/)[\w-]*requirements([-._]\w+)?\.(txt|pip)$")
    assert default.search(REQUIREMENTS)
    assert RENOVATE.get("pip_requirements", {}).get("enabled", True)



def test_linters_run_from_images_pinned_by_digest() -> None:
    steps = [s for job in workflow("lint-actions.yml")["jobs"].values() for s in job["steps"]]
    images = [s["uses"] for s in steps if s.get("uses", "").startswith("docker://")]
    assert {re.sub(r"[:@].*", "", i.rsplit("/", 1)[-1]) for i in images} == {"actionlint", "zizmor"}
    for image in images:
        assert re.search(r":[0-9][^@]*@sha256:[0-9a-f]{64}$", image), image


def test_actionlint_knows_every_runner_label() -> None:
    config = yaml.safe_load((ROOT / ".github" / "actionlint.yaml").read_text(encoding="utf-8"))
    labels = set(config["self-hosted-runner"]["labels"])
    used = {job["runs-on"] for path in all_workflows() for job in yaml.safe_load(path.read_text())["jobs"].values() if "runs-on" in job}
    assert "ubuntu-26.04" in used and "ubuntu-26.04" in labels


NIGHTLY = workflow("build.yml")["jobs"]["nightly-status"]
STATUS_JOBS = {
    "build.yml": ("nightly-status", "${{ !cancelled() && github.event_name == 'schedule' }}"),
    "track-junctions.yml": ("status", "${{ !cancelled() }}"),
    "track-binaries.yml": ("status", "${{ !cancelled() }}"),
}


@pytest.mark.parametrize("name", sorted(STATUS_JOBS))
def test_status_jobs_hold_issues_write_only_and_run_the_shared_script(name: str) -> None:
    wf = workflow(name)
    job_name, cond = STATUS_JOBS[name]
    job = wf["jobs"][job_name]
    assert job["if"] == cond
    assert job["permissions"] == {"issues": "write"}
    if name == "build.yml":
        assert {"build", "boot-test"} <= set(job["needs"])
    else:
        assert set(job["needs"]) == set(wf["jobs"]) - {job_name}, "every other job reports"
    checkout, report = job["steps"]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["sparse-checkout"] == ".github/scripts/tracking-issue.sh"
    assert report["run"].startswith("bash .github/scripts/tracking-issue.sh ")
    assert "${{" not in report["run"], "context goes through env:, not inline"
    assert report["env"]["FAILED"] == "${{ contains(needs.*.result, 'failure') }}"


FAKE_GH = """#!/usr/bin/env bash
args="$*"
printf '%s\\n' "${args//$'\\n'/ }" >> "${GH_LOG}"
if [ "$1 $2" = "issue list" ]; then
  printf '%s' "${GH_OPEN_ISSUE}"
fi
"""


@pytest.mark.parametrize(
    ("failed", "open_issue", "expected"),
    [
        ("true", "", "issue create --title Nightly build failing"),
        ("true", "42", "issue comment 42 --body Failed again: https://run"),
        ("false", "42", "issue close 42 --comment The nightly build of main passes again: https://run"),
        ("false", "", None),
    ],
)
def test_nightly_status_script(tmp_path: Path, failed: str, open_issue: str, expected: str | None) -> None:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(0o755)
    log = tmp_path / "gh.log"
    env = {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "GH_LOG": str(log),
        "GH_OPEN_ISSUE": open_issue,
        "FAILED": failed,
        "RUN_URL": "https://run",
    }
    subprocess.run(["bash", "-c", NIGHTLY["steps"][1]["run"]], env=env, check=True, cwd=ROOT)
    calls = log.read_text().splitlines()
    assert calls[0].startswith("issue list --state open")
    if expected is None:
        assert calls[1:] == []
    else:
        assert len(calls) == 2 and calls[1].startswith(expected), calls
