"""Prevent automatic updates that would merge incompatible kernel module indexes."""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
GUARD = ROOT / "files/os/update-check/usr/libexec/bluefin-sysupdate-feature-guard"
DROPIN = ROOT / "files/os/systemd/system/systemd-sysupdate.service.d/15-feature-conflict.conf"


@pytest.mark.parametrize(
    "zfs,nvidia,expected",
    [("yes", "yes", 1), ("yes", "no", 0), ("no", "yes", 0), ("no", "no", 0)],
)
def test_conflicting_features_are_rejected_before_update(tmp_path: Path, zfs: str, nvidia: str, expected: int) -> None:
    (tmp_path / "nvidia-open-595.feature").touch()
    updatectl = tmp_path / "updatectl"
    updatectl.write_text(
        "#!/bin/sh\n"
        "case \"$3\" in\n"
        f"  zfs) echo 'Enabled {zfs}' ;;\n"
        f"  nvidia-open-595) echo 'Enabled {nvidia}' ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n"
    )
    updatectl.chmod(0o755)
    result = subprocess.run(
        ["sh", str(GUARD)],
        env={**os.environ, "BLUEFIN_UPDATECTL": str(updatectl), "BLUEFIN_SYSUPDATE_FEATURE_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == expected, result.stderr
    if expected:
        assert "disable one with updatectl disable" in result.stderr


def test_missing_feature_is_not_an_error_on_older_releases(tmp_path: Path) -> None:
    result = subprocess.run(
        ["sh", str(GUARD)],
        env={**os.environ, "BLUEFIN_SYSUPDATE_FEATURE_DIR": str(tmp_path), "BLUEFIN_UPDATECTL": "/does/not/exist"},
        check=False,
    )
    assert result.returncode == 0


def test_updatectl_failure_prevents_staging(tmp_path: Path) -> None:
    (tmp_path / "nvidia-open-595.feature").touch()
    result = subprocess.run(
        ["sh", str(GUARD)],
        env={**os.environ, "BLUEFIN_SYSUPDATE_FEATURE_DIR": str(tmp_path), "BLUEFIN_UPDATECTL": "/does/not/exist"},
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0


def test_guard_is_wired_before_sysupdate(tmp_path: Path) -> None:
    assert "ExecCondition=/usr/libexec/bluefin-sysupdate-feature-guard" in DROPIN.read_text()
    assert "path: files/os/update-check" in (ROOT / "elements/bluefin-server/os-update-check.bst").read_text()
