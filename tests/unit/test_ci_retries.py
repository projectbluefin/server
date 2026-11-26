"""Network steps in CI retry, and the retry helper behaves.

A dropped connection or a 5xx from an apt mirror or GitHub is not a failed
build. scripts/ci/retry.sh wraps the commands that fetch; apt-get is wrapped
because its own Acquire::Retries does not retry a 503 on an index (measured on
Ubuntu 26.04: the same requests with Acquire::Retries=0 and =3).

Only steps safe to run twice are wrapped: downloads and package installs. The
steps that publish (oras push, gh release create) are not, and the release
script has its own, checked retry around uploading.
"""


import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
RETRY = ROOT / "scripts" / "ci" / "retry.sh"
WORKFLOWS = ROOT / ".github" / "workflows"
FILES = [*WORKFLOWS.glob("*.yml"), *(ROOT / "scripts" / "ci").glob("*.sh")]


def retry(*args: str, tmp: Path, **env: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(RETRY), *args],
        env={**os.environ, "RETRY_DELAY": "0", **env},
        capture_output=True, text=True, cwd=tmp, check=False,
    )


def flaky(tmp: Path, succeed_on: int) -> list[str]:
    """A command that fails until its Nth run, counting runs in a file."""
    counter = tmp / "runs"
    return ["bash", "-c", f'n=$(( $(cat {counter} 2>/dev/null || echo 0) + 1 )); echo $n > {counter}; [ $n -ge {succeed_on} ]']


def runs(tmp: Path) -> int:
    return int((tmp / "runs").read_text())


def test_a_command_that_works_runs_once(tmp_path: Path) -> None:
    result = retry(*flaky(tmp_path, 1), tmp=tmp_path)
    assert result.returncode == 0
    assert runs(tmp_path) == 1
    assert "Retrying" not in result.stderr


def test_a_command_that_fails_twice_then_works_succeeds(tmp_path: Path) -> None:
    result = retry(*flaky(tmp_path, 3), tmp=tmp_path)
    assert result.returncode == 0
    assert runs(tmp_path) == 3
    assert result.stderr.count("::warning title=Retrying::") == 2


def test_a_command_that_keeps_failing_fails_with_its_own_status(tmp_path: Path) -> None:
    result = retry("sh", "-c", "exit 7", tmp=tmp_path)
    assert result.returncode == 7
    assert "::error::sh failed after 3 attempts (exit 7)" in result.stderr


def test_the_attempt_count_can_be_set(tmp_path: Path) -> None:
    result = retry("-n", "5", *flaky(tmp_path, 99), tmp=tmp_path)
    assert result.returncode != 0
    assert runs(tmp_path) == 5


@pytest.mark.parametrize("args", [["-n", "0", "true"], ["-n", "x", "true"], []])
def test_a_bad_call_is_refused_before_anything_runs(tmp_path: Path, args: list[str]) -> None:
    assert retry(*args, tmp=tmp_path).returncode == 2


def test_the_wait_grows_with_the_attempt(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "sleep").write_text(f'#!/bin/bash\necho "$1" >> {tmp_path}/sleeps\n')
    (bin_dir / "sleep").chmod(0o755)
    retry("false", tmp=tmp_path, RETRY_DELAY="4", PATH=f"{bin_dir}:{os.environ['PATH']}")
    assert (tmp_path / "sleeps").read_text().split() == ["4", "8"]


def test_every_apt_get_in_ci_goes_through_the_retry_helper() -> None:
    for path in FILES:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"\bapt-get\b", line) and not line.lstrip().startswith("#"):
                assert "retry.sh" in line or "${retry}" in line, f"{path.relative_to(ROOT)}:{number}: {line.strip()}"


def test_the_large_release_download_retries_and_overwrites_a_partial_file() -> None:
    text = (WORKFLOWS / "e2e-opt-in.yml").read_text(encoding="utf-8")
    assert 'bash scripts/ci/retry.sh gh release download "${TAG}" --clobber --dir dist/release' in text


def test_publishing_steps_are_never_wrapped() -> None:
    # A push or a release that half worked must not be run blindly again.
    for path in FILES:
        for line in path.read_text(encoding="utf-8").splitlines():
            if "retry.sh" in line:
                assert not re.search(r"oras (push|login)|release create|release edit|release delete", line), line
