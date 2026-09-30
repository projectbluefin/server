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
    assert publish_commands(RELEASE) == ["verify", "release", "oci"]
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


def test_build_and_dry_run_check_out_the_triggering_commit() -> None:
    for job in (JOBS["build"], DRY_RUN):
        checkout = steps(job, "actions/checkout@")[0]["with"]
        assert checkout["ref"] == "${{ github.event.pull_request.head.sha || github.sha }}"


def test_dry_run_is_read_only_and_secret_free() -> None:
    assert DRY_RUN["if"] == "${{ github.event_name == 'pull_request' }}"
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
