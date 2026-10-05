"""CI workflow contracts that span files.

- reproducibility.yml rebuilds everything that ships: every element
  oci/bluefin-server-image.bst stages into the release set and every oci/*
  target `just validate` resolves is in FINAL_ASSEMBLY, or its cached
  artifact would be reused by the second build and never compared.
- The runner disk setup lives in scripts/ci-runner-disk.sh only, and is safe
  to run twice.
- Every workflow installs the same `just` version.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
IMAGE = ROOT / "elements" / "oci" / "bluefin-server-image.bst"
DISK_SCRIPT = ROOT / "scripts" / "ci-runner-disk.sh"


def final_assembly() -> set[str]:
    job = yaml.safe_load((WORKFLOWS / "reproducibility.yml").read_text())["jobs"]["reproducibility"]
    return set(job["env"]["FINAL_ASSEMBLY"].split())


def staged_into_release_set() -> set[str]:
    """Dependencies the image element stages at a location: its payload."""
    element = yaml.safe_load(IMAGE.read_text())
    deps = element.get("build-depends", []) + element.get("depends", [])
    return {d["filename"] for d in deps if isinstance(d, dict) and "location" in d.get("config", {})}


def validate_targets() -> set[str]:
    recipe = (ROOT / "Justfile").read_text().split("\nvalidate:", 1)[1].split("\n\n", 1)[0]
    return set(re.findall(r"\boci/[\w.-]+\.bst\b", recipe))


def test_shipped_set_is_derived_from_the_build() -> None:
    staged, validated = staged_into_release_set(), validate_targets()
    assert {"oci/bluefin-server-usr.bst", "oci/bluefin-server-sbom.bst", "oci/nvidia-open-595-sysext.bst"} <= staged
    assert "oci/bluefin-server-image.bst" in validated
    assert "oci/nvidia-container-toolkit-sysext.bst" in validated


def test_reproducibility_rebuilds_everything_that_ships() -> None:
    missing = (staged_into_release_set() | validate_targets()) - final_assembly()
    assert not missing, f"add to FINAL_ASSEMBLY in reproducibility.yml: {sorted(missing)}"


def test_final_assembly_names_real_elements_and_keeps_the_efi_keys() -> None:
    for element in final_assembly():
        assert (ROOT / "elements" / element).is_file(), element
    # sbvarsign stamps the current time into PK/KEK/db.auth; see the header.
    assert "bluefin-server/keys/efi-keys.bst" not in final_assembly()


@pytest.mark.parametrize("workflow", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_runner_disk_setup_is_not_inlined(workflow: str) -> None:
    text = (WORKFLOWS / workflow).read_text()
    assert "graphroot" not in text and "ln -sf" not in text, f"{workflow}: use scripts/ci-runner-disk.sh"


def test_every_build_job_sets_up_the_runner_disk() -> None:
    for workflow, job in (("build.yml", "kernel-cache"), ("build.yml", "build"),
                          ("reproducibility.yml", "reproducibility")):
        steps = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]["steps"]
        assert any(s.get("run") == "bash scripts/ci-runner-disk.sh" for s in steps), f"{workflow}:{job}"


def test_every_workflow_installs_the_same_just() -> None:
    pins = {m for p in WORKFLOWS.glob("*.yml") for m in re.findall(r"tool: (just@\S+)", p.read_text())}
    assert len(pins) == 1, pins


@pytest.fixture
def runner(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
    (bin_dir / "sudo").chmod(0o755)
    (tmp_path / "home").mkdir()
    return {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "HOME": str(tmp_path / "home"),
            "CI_RUNNER_MNT": str(tmp_path / "mnt")}


def test_runner_disk_moves_podman_and_buildstream_to_mnt(runner: dict[str, str]) -> None:
    for _ in range(2):
        subprocess.run(["bash", str(DISK_SCRIPT)], env=runner, check=True)
    home, mnt = Path(runner["HOME"]), Path(runner["CI_RUNNER_MNT"])
    conf = (home / ".config" / "containers" / "storage.conf").read_text()
    assert f'graphroot = "{mnt}/podman"' in conf
    assert f'runroot = "/run/user/{os.getuid()}"' in conf and 'driver = "overlay"' in conf
    cache = home / ".cache" / "buildstream"
    assert cache.is_symlink() and os.readlink(cache) == f"{mnt}/buildstream"
    # `ln -sf` on the second run would have put a link inside the target.
    assert list((mnt / "buildstream").iterdir()) == []
    assert (mnt / "podman").is_dir()
