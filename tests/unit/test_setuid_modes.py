"""Setuid/setgid bits survive the BuildStream artifact round trip into the DDI.

BuildStream artifacts record one executable bit per file (REAPI
``FileNode.is_executable``), so every file flatcar-usr.bst extracts is staged
into the DDI build at 0644/0755. Flatcar ships ``sudo``, ``su``, ``passwd``,
``mount`` and friends setuid root; without a fix the installed image has
``/usr/bin/sudo`` at 0755 and sudo refuses to run. flatcar-usr.bst records the
modes in ``usr/lib/bluefin-server/setuid-modes`` and bluefin-server-ddi.bst
restores them before ``mkfs.xfs -p`` copies the tree.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DDI_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-ddi.bst"
FLATCAR_USR_ELEMENT = REPO_ROOT / "elements" / "flatcar" / "flatcar-usr.bst"


def _ddi_script() -> str:
    data = yaml.safe_load(DDI_ELEMENT.read_text(encoding="utf-8"))
    return "\n".join(data["config"]["commands"])


def _restore_block(script: str) -> str:
    """From the manifest assignment to the `ls -l sudo` that logs the restored tree."""
    start = script.index("SETUID_MODES=/layer/usr/lib/bluefin-server/setuid-modes")
    end = script.index("ls -l /layer/usr/bin/sudo\n") + len("ls -l /layer/usr/bin/sudo\n")
    return script[start:end]


def _run_restore(tmp_path: Path, manifest: str | None, sudo_mode: int = 0o755) -> tuple[Path, subprocess.CompletedProcess]:
    layer = tmp_path / "layer"
    for rel, mode in (
        ("usr/bin/sudo", sudo_mode),
        ("usr/bin/su", 0o755),
        ("usr/bin/unix_chkpwd", 0o755),
        ("usr/libexec/dbus-daemon-launch-helper", 0o644),
        ("usr/bin/bash", 0o755),
    ):
        path = layer / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("mock", encoding="utf-8")
        path.chmod(mode)
    (layer / "usr" / "lib" / "bluefin-server").mkdir(parents=True)
    if manifest is not None:
        (layer / "usr" / "lib" / "bluefin-server" / "setuid-modes").write_text(manifest, encoding="utf-8")
    block = _restore_block(_ddi_script()).replace("/layer", str(layer))
    result = subprocess.run(["bash", "-euo", "pipefail", "-c", block], capture_output=True, text=True)
    return layer, result


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_flatcar_usr_records_and_ddi_restores_the_same_file() -> None:
    flatcar_usr = FLATCAR_USR_ELEMENT.read_text(encoding="utf-8")
    ddi = DDI_ELEMENT.read_text(encoding="utf-8")

    assert "find \"%{install-root}/usr\" -type f -perm /6000 -printf '%m usr/%P\\n'" in flatcar_usr
    assert '"%{install-root}/usr/lib/bluefin-server/setuid-modes"' in flatcar_usr
    assert "SETUID_MODES=/layer/usr/lib/bluefin-server/setuid-modes" in ddi
    # Restoration happens after the tree is final and before the image is cut,
    # and the written image is checked with xfs_db afterwards, so a green build
    # proves the mode reached the DDI (BuildStream hides element output on
    # success, so the ls -l/cat lines alone would prove nothing).
    script = _ddi_script()
    mkfs = script.index("mkfs.xfs -f -L bluefin-root")
    assert script.index('depmod -b /layer/usr "${KVER}"') < script.index("SETUID_MODES=") < mkfs
    xfs_db = script.index("xfs_db -r -c 'path /usr/bin/sudo' -c 'print core.mode'")
    assert mkfs < xfs_db < script.index("zstd --rm")
    assert '"core.mode = 0104755")' in script
    # The manifest is recorded after flatcar-usr's removals, never before.
    assert flatcar_usr.index('rm -r "%{install-root}/usr/lib/systemd/system/systemd-fsck@') < flatcar_usr.index("-printf '%m usr/%P")


def test_ddi_restores_every_recorded_mode(tmp_path: Path) -> None:
    layer, result = _run_restore(
        tmp_path,
        "2755 usr/bin/unix_chkpwd\n"
        "4110 usr/libexec/dbus-daemon-launch-helper\n"
        "4755 usr/bin/su\n"
        "4755 usr/bin/sudo\n",
    )
    assert result.returncode == 0, result.stderr
    assert _mode(layer / "usr/bin/sudo") == 0o4755
    assert _mode(layer / "usr/bin/su") == 0o4755
    assert _mode(layer / "usr/bin/unix_chkpwd") == 0o2755
    # 4110 (---s--x---) gains owner read: mkfs.xfs -p must be able to open the
    # file under buildbox-fuse, which enforces the mode bits itself (the
    # round-1 CI build failed with "Permission denied" on exactly this file).
    assert _mode(layer / "usr/libexec/dbus-daemon-launch-helper") == 0o4510
    assert "NOTE: usr/libexec/dbus-daemon-launch-helper recorded without owner read; applying 4510" in result.stdout
    assert _mode(layer / "usr/bin/bash") == 0o755


def test_ddi_fails_when_the_manifest_is_missing(tmp_path: Path) -> None:
    layer, result = _run_restore(tmp_path, None)
    assert result.returncode == 1
    assert "setuid-modes is missing or empty" in result.stderr
    assert _mode(layer / "usr/bin/sudo") == 0o755


def test_ddi_fails_when_the_manifest_is_empty(tmp_path: Path) -> None:
    _, result = _run_restore(tmp_path, "")
    assert result.returncode == 1
    assert "setuid-modes is missing or empty" in result.stderr


def test_ddi_fails_when_the_manifest_lists_a_missing_file(tmp_path: Path) -> None:
    layer, result = _run_restore(tmp_path, "4755 usr/bin/sudo\n4755 usr/bin/gone\n")
    assert result.returncode == 1
    assert "setuid-modes lists usr/bin/gone but it is not in" in result.stderr
    assert "stale manifest" in result.stderr


def test_ddi_logs_the_restored_modes(tmp_path: Path) -> None:
    _, result = _run_restore(tmp_path, "4755 usr/bin/su\n4755 usr/bin/sudo\n")
    assert result.returncode == 0, result.stderr
    assert "Restored 2 setuid/setgid modes" in result.stdout
    assert "4755 usr/bin/sudo" in result.stdout
    assert "-rwsr-xr-x" in result.stdout


def test_ddi_fails_when_sudo_is_still_not_setuid(tmp_path: Path) -> None:
    _, result = _run_restore(tmp_path, "4755 usr/bin/su\n")
    assert result.returncode == 1
    assert "/usr/bin/sudo is mode 755" in result.stderr
