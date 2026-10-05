"""scripts/ci-runner-disk.sh is the one runner disk setup, and is safe to run twice."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
DISK_SCRIPT = ROOT / "scripts" / "ci-runner-disk.sh"


@pytest.mark.parametrize("workflow", sorted(p.name for p in WORKFLOWS.glob("*.yml")))
def test_runner_disk_setup_is_not_inlined(workflow: str) -> None:
    text = (WORKFLOWS / workflow).read_text()
    assert "graphroot" not in text and "ln -sf" not in text, f"{workflow}: use scripts/ci-runner-disk.sh"


def test_every_build_job_sets_up_the_runner_disk() -> None:
    for workflow, job in (("build.yml", "kernel-cache"), ("build.yml", "build"),
                          ("reproducibility.yml", "reproducibility")):
        steps = yaml.safe_load((WORKFLOWS / workflow).read_text())["jobs"][job]["steps"]
        assert any(s.get("run") == "bash scripts/ci-runner-disk.sh" for s in steps), f"{workflow}:{job}"


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
