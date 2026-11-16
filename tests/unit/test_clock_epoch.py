"""The image clock floor follows the SDK release, not BuildStream's 2011 epoch."""

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-release.bst"


@pytest.mark.parametrize(
    ("sdk", "expected"),
    [("26.08.3", datetime(2026, 8, 1, tzinfo=UTC)), ("27.02.1", datetime(2027, 2, 1, tzinfo=UTC))],
)
def test_image_clock_epoch_tracks_sdk_release(tmp_path: Path, sdk: str, expected: datetime) -> None:
    commands = yaml.safe_load(ELEMENT.read_text())["config"]["install-commands"]
    script = "\n".join(commands)
    for key, value in {
        "install-root": str(tmp_path),
        "image-version": "0.1",
        "systemd-arch": "x86-64",
        "installer-version": sdk,
    }.items():
        script = script.replace(f"%{{{key}}}", value)
    subprocess.run(["bash", "-eu", "-c", script], check=True, capture_output=True, text=True)
    epoch = int((tmp_path / "usr/lib/clock-epoch").read_text())
    assert epoch == int(expected.timestamp())
    assert int((tmp_path / "usr/lib/clock-epoch").stat().st_mtime) == int(expected.timestamp())
