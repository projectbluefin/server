"""The two small root helpers around the Homebrew system container.

files/homebrew-image/bluefin-homebrew-image (bluefin-homebrew-image.service,
`ExecStart=... %A`) points /var/lib/machines/bluefin-homebrew.raw at the
machine image for the booted IMAGE_VERSION. The version is part of a path it
links as root, so anything outside `just set-version`'s format must be
refused before it touches the filesystem, and a missing image must fail the
unit rather than leave a dangling link.

files/homebrew/bluefin-homebrew-ready (bluefin-homebrew.service
ExecStartPost) holds the unit in "activating" until the guest writes
/run/bluefin-homebrew.ready: it polls once a second, 60 times, and fails the
start otherwise.

Both run with stubs: bluefin-homebrew-image from a copy whose
/var/lib/machines is a temporary directory, bluefin-homebrew-ready with
systemd-run and sleep stubbed on PATH.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
IMAGE = ROOT / "files" / "homebrew-image" / "bluefin-homebrew-image"
IMAGE_SERVICE = ROOT / "files" / "homebrew-image" / "bluefin-homebrew-image.service"
READY = ROOT / "files" / "homebrew" / "bluefin-homebrew-ready"
HOMEBREW_SERVICE = ROOT / "files" / "homebrew" / "systemd" / "bluefin-homebrew.service"
MACHINES = "/var/lib/machines"


@pytest.fixture
def machines(tmp_path: Path) -> Path:
    d = tmp_path / "machines"
    d.mkdir()
    return d


def select(tmp_path: Path, machines: Path, *args: str) -> subprocess.CompletedProcess:
    text = IMAGE.read_text()
    assert text.count(MACHINES) == 2, "the copy below must redirect every machine path"
    script = tmp_path / "bluefin-homebrew-image"
    script.write_text(text.replace(MACHINES, str(machines)))
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True)


def test_service_passes_the_booted_image_version() -> None:
    assert "ExecStart=/usr/libexec/bluefin-homebrew-image %A\n" in IMAGE_SERVICE.read_text()


def test_version_format_matches_set_version() -> None:
    # The guard only lets through what `just set-version` writes; if the two
    # drift, a valid release could no longer select its Homebrew machine.
    pattern = r"=~ (\^\[0-9\]\[0-9A-Za-z\.\]\{0,16\}\$) \]\]"
    shipped = re.search(pattern, IMAGE.read_text())
    recipe = re.search(pattern, (ROOT / "Justfile").read_text())
    assert shipped and recipe and shipped.group(1) == recipe.group(1)


@pytest.mark.parametrize("version", ["26.09.2", "26.10.1a", "1", "1" * 17])
def test_links_the_machine_image_for_the_version(tmp_path: Path, machines: Path, version: str) -> None:
    (machines / f"homebrew_{version}.raw").write_text("img")
    result = select(tmp_path, machines, version)
    assert result.returncode == 0, result.stderr
    link = machines / "bluefin-homebrew.raw"
    assert link.is_symlink()
    assert os.readlink(link) == f"homebrew_{version}.raw", "relative, inside the machines directory"


def test_relinks_over_the_previous_version(tmp_path: Path, machines: Path) -> None:
    for v in ("26.09.1", "26.09.2"):
        (machines / f"homebrew_{v}.raw").write_text(v)
    assert select(tmp_path, machines, "26.09.1").returncode == 0
    result = select(tmp_path, machines, "26.09.2")
    assert result.returncode == 0, result.stderr
    assert os.readlink(machines / "bluefin-homebrew.raw") == "homebrew_26.09.2.raw"
    assert (machines / "homebrew_26.09.1.raw").read_text() == "26.09.1", "old image untouched"


def test_missing_image_fails_without_linking(tmp_path: Path, machines: Path) -> None:
    result = select(tmp_path, machines, "26.09.2")
    assert result.returncode == 1
    assert f"Homebrew machine missing: {machines}/homebrew_26.09.2.raw" in result.stderr
    assert not (machines / "bluefin-homebrew.raw").is_symlink()


def test_missing_image_keeps_the_current_link(tmp_path: Path, machines: Path) -> None:
    (machines / "homebrew_26.09.1.raw").write_text("img")
    assert select(tmp_path, machines, "26.09.1").returncode == 0
    assert select(tmp_path, machines, "26.09.2").returncode == 1
    assert os.readlink(machines / "bluefin-homebrew.raw") == "homebrew_26.09.1.raw"


def test_no_version_is_a_usage_error(tmp_path: Path, machines: Path) -> None:
    result = select(tmp_path, machines)
    assert result.returncode != 0
    assert "missing host image version" in result.stderr
    assert list(machines.iterdir()) == []


@pytest.mark.parametrize(
    "version",
    [
        "",
        "v26.09.2",  # must start with a digit
        "1" * 18,  # longer than set-version allows
        "26.09.2/../../x",
        "../homebrew_1",
        "26.09-2",
        "26.09.2 ",
        "26.09.2\n",
        "26.09.2*",
    ],
)
def test_refuses_versions_outside_the_release_format(tmp_path: Path, machines: Path, version: str) -> None:
    # Plant the image the version names where it can exist, so only the guard
    # stops the link.
    if version and "/" not in version:
        (machines / f"homebrew_{version}.raw").write_text("img")
    result = select(tmp_path, machines, version)
    assert result.returncode != 0
    assert not (machines / "bluefin-homebrew.raw").exists()
    assert not (machines / "bluefin-homebrew.raw").is_symlink()


SYSTEMD_RUN = """#!/bin/sh
echo "$*" >> "$LOG/systemd-run"
n=$(wc -l < "$LOG/systemd-run")
[ "$n" -ge "$READY_AT" ]
"""

SLEEP = """#!/bin/sh
echo "$*" >> "$LOG/sleep"
"""


def ready(tmp_path: Path, ready_at: int) -> tuple[subprocess.CompletedProcess, list[str], list[str]]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in (("systemd-run", SYSTEMD_RUN), ("sleep", SLEEP)):
        (bindir / name).write_text(body)
        (bindir / name).chmod(0o755)
    log = tmp_path / "log"
    log.mkdir()
    (log / "systemd-run").touch()
    (log / "sleep").touch()
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "LOG": str(log), "READY_AT": str(ready_at)}
    result = subprocess.run(["bash", str(READY)], env=env, capture_output=True, text=True, timeout=60)
    return result, (log / "systemd-run").read_text().splitlines(), (log / "sleep").read_text().splitlines()


def test_ready_runs_after_the_container_starts() -> None:
    assert "ExecStartPost=/usr/libexec/bluefin-homebrew-ready\n" in HOMEBREW_SERVICE.read_text()


def test_ready_at_once_probes_the_guest_marker_once(tmp_path: Path) -> None:
    result, probes, sleeps = ready(tmp_path, 1)
    assert result.returncode == 0, result.stderr
    assert probes == [
        "--machine=bluefin-homebrew --pipe --wait --quiet --expand-environment=no "
        "/usr/bin/test -f /run/bluefin-homebrew.ready"
    ]
    assert sleeps == []


def test_ready_waits_a_second_between_probes(tmp_path: Path) -> None:
    result, probes, sleeps = ready(tmp_path, 4)
    assert result.returncode == 0, result.stderr
    assert len(probes) == 4
    assert sleeps == ["1"] * 3


def test_ready_on_the_last_attempt_still_succeeds(tmp_path: Path) -> None:
    result, probes, _ = ready(tmp_path, 60)
    assert result.returncode == 0, result.stderr
    assert len(probes) == 60


def test_never_ready_fails_the_start_after_60_probes(tmp_path: Path) -> None:
    result, probes, sleeps = ready(tmp_path, 61)
    assert result.returncode == 1
    assert len(probes) == 60
    assert len(sleeps) == 60
    assert "Homebrew guest user managers failed to become ready" in result.stderr


def test_ready_poll_fits_inside_the_unit_start_timeout() -> None:
    # 60 one-second polls plus the container boot must fit TimeoutStartSec.
    timeout = re.search(r"^TimeoutStartSec=(\d+)$", HOMEBREW_SERVICE.read_text(), re.MULTILINE)
    assert timeout and int(timeout.group(1)) > 60
