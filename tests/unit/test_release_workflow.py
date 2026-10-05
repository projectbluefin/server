"""The release job and its pull-request rehearsal run the same publish path."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))
JOBS = WORKFLOW["jobs"]
RELEASE = JOBS["release"]
DRY_RUN = JOBS["release-dry-run"]


def steps(job: dict, uses_prefix: str) -> list[dict]:
    return [s for s in job["steps"] if s.get("uses", "").startswith(uses_prefix)]


def publish_commands(job: dict) -> list[str]:
    commands = []
    for step in job["steps"]:
        for line in step.get("run", "").splitlines():
            if "scripts/publish-release.sh" in line:
                commands.append(line.split("scripts/publish-release.sh", 1)[1].split()[0])
    return commands


def test_both_jobs_publish_through_the_script_only() -> None:
    assert publish_commands(RELEASE) == ["verify", "taggable", "release", "oci"]
    assert publish_commands(DRY_RUN) == ["verify", "release", "oci"]
    for job in (RELEASE, DRY_RUN):
        runs = "\n".join(s.get("run", "") for s in job["steps"])
        assert "oras push" not in runs
        assert "gh release create" not in runs


def test_oras_is_pinned_identically_in_both_jobs() -> None:
    pins = [json.dumps({"uses": s["uses"], "with": s["with"]}, sort_keys=True) for job in (RELEASE, DRY_RUN) for s in steps(job, "oras-project/setup-oras@")]
    assert len(pins) == 2
    assert pins[0] == pins[1]
    assert "checksum" in json.loads(pins[0])["with"]


def test_build_boot_test_and_dry_run_check_out_the_triggering_commit() -> None:
    # Not the branch tip: main runs queue, so a tip checkout could pair one
    # commit's image set with a later commit's boot-test harness.
    for name in ("build", "boot-test", "release-dry-run"):
        checkout = steps(JOBS[name], "actions/checkout@")[0]["with"]
        assert checkout["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}", name
        assert checkout["repository"] == "${{ github.event.pull_request.head.repo.full_name || github.repository }}", name


def test_dry_run_is_read_only_and_secret_free() -> None:
    assert "github.event_name == 'pull_request'" in DRY_RUN["if"]
    assert DRY_RUN["permissions"] == {"contents": "read"}
    assert "secrets." not in json.dumps(DRY_RUN)
    assert "@sha256:" in DRY_RUN["services"]["registry"]["image"]
    oci = [s["run"] for s in DRY_RUN["steps"] if "publish-release.sh oci" in s.get("run", "")]
    assert oci and "--plain-http" in oci[0] and "--pull-back" in oci[0]
    render = [s["run"] for s in DRY_RUN["steps"] if "publish-release.sh release" in s.get("run", "")]
    assert render and render[0].rstrip().endswith("--dry-run")


def test_release_attests_files_and_oci_artifact() -> None:
    attest = steps(RELEASE, "actions/attest@")
    assert len({s["uses"] for s in attest}) == 1
    subjects = [s["with"] for s in attest]
    assert sum("subject-checksums" in w and "sbom-path" not in w for w in subjects) == 1
    assert sum("subject-checksums" in w and "sbom-path" in w for w in subjects) == 1
    oci = [w for w in subjects if "subject-digest" in w]
    assert len(oci) == 2 and all(w["push-to-registry"] is True for w in oci)
    assert RELEASE["permissions"]["id-token"] == "write"
    assert RELEASE["permissions"]["attestations"] == "write"
    assert not any("id-token" in (job.get("permissions") or {}) for name, job in JOBS.items() if name != "release")


def test_pushes_to_main_never_cancel_a_release_run() -> None:
    concurrency = WORKFLOW["concurrency"]
    assert concurrency["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"


def test_boot_test_uploads_every_harness_log_directory() -> None:
    upload = next(s for s in WORKFLOW["jobs"]["boot-test"]["steps"] if s.get("name") == "Upload boot logs")
    paths = upload["with"]["path"].split()
    for d in ("dist/dogfood-install/", "dist/dogfood-installer/"):
        assert any(p.startswith(d) for p in paths), d


def test_release_publishes_only_a_built_and_boot_tested_set() -> None:
    # Explicit results instead of !failure(): a failed kernel-cache must not
    # block the release, and a skipped or failed build or boot-test must.
    cond = RELEASE["if"]
    assert "!failure()" not in cond
    for part in (
        "!cancelled()",
        "needs.changes.outputs.release == 'true'",
        "needs.build.result == 'success'",
        "needs.boot-test.result == 'success'",
    ):
        assert part in cond
    assert RELEASE["needs"] == ["changes", "build", "boot-test"]


def test_a_failed_kernel_cache_seed_is_reported() -> None:
    seed = next(s for s in JOBS["kernel-cache"]["steps"] if s.get("id") == "seed")
    assert seed["continue-on-error"] is True
    report = next(s for s in JOBS["kernel-cache"]["steps"] if s.get("if") == "steps.seed.outcome == 'failure'")
    assert "::warning" in report["run"] and "GITHUB_STEP_SUMMARY" in report["run"]


def test_jobs_after_build_run_when_kernel_cache_is_skipped() -> None:
    # kernel-cache only runs for release builds; without an explicit check of
    # build's result, a skipped kernel-cache skips every job downstream of build.
    for name in ("boot-test", "release-dry-run"):
        cond = JOBS[name].get("if", "")
        assert "!cancelled()" in cond and "needs.build.result == 'success'" in cond, name


def test_release_publishes_nothing_once_the_commit_cannot_be_tagged() -> None:
    names = [s.get("name") for s in RELEASE["steps"]]
    check = names.index("Check this commit can still be tagged")
    step = RELEASE["steps"][check]
    assert step["id"] == "taggable" and "if" not in step
    assert step["env"] == {"GH_TOKEN": "${{ github.token }}"}
    assert "verify" in RELEASE["steps"][check - 1].get("run", "")
    for later in RELEASE["steps"][check + 1 :]:
        assert later.get("if") == "steps.taggable.outputs.publish == 'true'", later.get("name")
    assert "taggable" not in json.dumps(DRY_RUN)
