"""Unit coverage for .github/scripts/image-build-needed.py.

The build workflow skips the ~2 h image build and the boot test for pull
requests the script classifies as not touching the image. A wrong `false`
merges an untested image change, so the invariants guarded here are that every
tracked file under a build input root, the build workflow and the classifier
always build, and that the workflow runs the base revision's classifier.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "image-build-needed.py"

_spec = importlib.util.spec_from_file_location("image_build_needed", SCRIPT)
image_build_needed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_build_needed)


def tracked_files():
    out = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line]


def test_every_build_input_builds():
    inputs = [
        p
        for p in tracked_files()
        if p.startswith(image_build_needed.BUILD_PREFIXES)
        or p in {"project.conf", "Justfile", ".github/workflows/build.yml"}
        or p.startswith(".github/scripts/check-")
    ]
    assert inputs, "git ls-files returned no build inputs"
    skipped = [p for p in inputs if not image_build_needed.needs_build(p)]
    assert skipped == []


def test_the_classifier_itself_builds():
    assert image_build_needed.needs_build(".github/scripts/image-build-needed.py")


@pytest.mark.parametrize("path", sorted(image_build_needed.GATE_FILES))
def test_gate_changes_build_even_among_docs(path):
    assert (ROOT / path).is_file(), f"{path} moved; update GATE_FILES"
    assert image_build_needed.needs_build(path)
    assert image_build_needed.image_build_needed(["docs/a.md", path])


def test_changes_job_runs_the_base_revision_classifier():
    workflow = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text())
    steps = workflow["jobs"]["changes"]["steps"]
    checkouts = [s for s in steps if str(s.get("uses", "")).startswith("actions/checkout@")]
    assert len(checkouts) == 1
    ref = checkouts[0]["with"]["ref"]
    assert ref == "${{ github.event.pull_request.base.sha }}"
    assert "repository" not in checkouts[0]["with"]
    run = "\n".join(s.get("run", "") for s in steps)
    assert "python3 .github/scripts/image-build-needed.py" in run


@pytest.mark.parametrize(
    "path",
    [
        "docs/skills/ci-tooling.md",
        "README.md",
        ".github/copilot-instructions.md",
        "tests/unit/test_repart_layout.py",
        "tests/unit/os-justfile_test.bats",
        ".github/scripts/docs-checks.py",
        ".github/workflows/unit-tests.yml",
    ],
)
def test_docs_and_unit_test_changes_skip(path):
    assert not image_build_needed.needs_build(path)


@pytest.mark.parametrize(
    "path",
    [
        "files/os/README.md",
        "elements/notes.md",
        "tests/fixtures/ignition/apply-marker.ign",
        "scripts/dogfood-diskless.sh",
        # The NVIDIA sysexts are part of the image set.
        "files/nvidia/sysext/nvidia-load.service",
        "files/nvidia-container-toolkit/sysext/nvidia-cdi-refresh-bluefin.conf",
        "elements/nvidia/nvidia-open-595.bst",
        "include/nvidia.yml",
        "include/nvidia-container-toolkit.yml",
        "renovate.json",
        "a-new-top-level-file",
    ],
)
def test_build_inputs_and_unknown_paths_build(path):
    assert image_build_needed.needs_build(path)


def test_one_build_input_among_docs_builds():
    assert image_build_needed.image_build_needed(["docs/a.md", "elements/x.bst"])


def test_empty_or_truncated_lists_build():
    assert image_build_needed.image_build_needed([])
    many = ["docs/x.md"] * image_build_needed.API_FILE_LIMIT
    assert image_build_needed.image_build_needed(many)


def test_cli_reads_stdin():
    def run(text):
        return subprocess.run(
            [sys.executable, str(SCRIPT)], input=text, capture_output=True, text=True, check=True
        ).stdout.strip()

    assert run("docs/skills/index.md\nREADME.md\n") == "false"
    assert run("docs/skills/index.md\nfiles/os/x\n") == "true"
