"""Installing onto a disk that is not empty (#359).

systemd-repart v261 erases the disk for sysinstall's --erase=yes but keeps the
kernel's partition devices of what the disk held, so adding the new ESP's
partition device (BLKPG) and rereading the new partition table failed with
EBUSY on any disk with partitions. The USB installer forgets those partition
devices (udev rule) before sysinstall starts; scripts/dogfood-installer.sh
replays the install onto such disks in QEMU (DOGFOOD_TARGET).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / "files" / "os" / "udev" / "rules.d" / "90-bluefin-installer-forget-partitions.rules"
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-udev-rules.bst"
OS_STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"
DROPIN = ROOT / "files" / "os" / "systemd" / "system" / "systemd-sysinstall.service.d" / "10-bluefin-installer.conf"
BOOT_ELEMENT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
DOGFOOD = ROOT / "scripts" / "dogfood-installer.sh"
JUSTFILE = ROOT / "Justfile"


def rules() -> list[str]:
    return [line for line in RULES.read_text(encoding="utf-8").splitlines() if line and not line.startswith("#")]


def test_the_rule_only_runs_in_the_installer_boot():
    # Installed and diskless nodes may use other disks' partitions (/var on
    # disk, data disks); only the installer UKI boots system-install.target.
    text = "\n".join(rules())
    assert 'IMPORT{cmdline}="systemd.unit"' in text
    assert 'ENV{systemd.unit}!="system-install.target", GOTO="bluefin_installer_end"' in text
    assert "system-install.target" in BOOT_ELEMENT.read_text(encoding="utf-8")


def test_the_rule_only_forgets_partition_devices_and_changes_no_disk():
    runs = [line for line in rules() if "RUN" in line]
    assert runs == ['RUN+="/usr/bin/partx --delete $devnode"']
    assert 'ENV{DEVTYPE}!="partition", GOTO="bluefin_installer_end"' in rules()


def test_the_stick_keeps_its_partitions():
    # Its usr (dm-verity) and ESP (/run/bluefin/installer) are the installer.
    assert 'ENV{ID_PART_ENTRY_NAME}=="bluefin-installer*", GOTO="bluefin_installer_end"' in rules()


def test_the_new_install_keeps_its_partitions():
    # repart and sysinstall add the target's new partition devices while
    # sysinstall runs; a marker in its RuntimeDirectory= marks that. The
    # marker is touched only after udev settled, so every old partition's add
    # event ran the rule first (RuntimeDirectory= itself exists before
    # ExecStartPre=).
    unit = SystemdFile(DROPIN)
    runtime = unit.value("Service", "RuntimeDirectory")
    assert runtime == "bluefin-sysinstall"
    marker = f"/run/{runtime}/started"
    assert unit.commands("ExecStartPre") == [
        ["/usr/bin/udevadm", "settle"],
        ["/usr/bin/touch", marker],
    ]
    assert f'TEST=="{marker}", GOTO="bluefin_installer_end"' in rules()
    # Every guard comes before the action.
    lines = rules()
    run = next(i for i, line in enumerate(lines) if line.startswith("RUN"))
    assert all("GOTO" not in line for line in lines[run:])


def test_the_rule_runs_after_blkid_labelled_the_partition():
    # ID_PART_ENTRY_NAME comes from 60-persistent-storage.rules.
    assert int(re.match(r"(\d+)-", RULES.name).group(1)) > 60


def test_the_rule_ships_in_the_os_image():
    element = ELEMENT.read_text(encoding="utf-8")
    assert "path: files/os/udev/rules.d" in element
    assert "target: /usr/lib/udev/rules.d" in element
    assert "- bluefin-server/os-udev-rules.bst" in OS_STACK.read_text(encoding="utf-8")


def run_dogfood(tmp_path: Path, **env: str) -> subprocess.CompletedProcess:
    image = tmp_path / "img"
    image.mkdir(exist_ok=True)
    return subprocess.run(
        ["bash", str(DOGFOOD), str(image)],
        env={**os.environ, "DOGFOOD_STATE": str(tmp_path / "state"), **env},
        capture_output=True,
        text=True,
    )


def test_an_unknown_target_kind_is_refused_before_anything_boots(tmp_path: Path):
    result = run_dogfood(tmp_path, DOGFOOD_TARGET="bogus")
    assert result.returncode != 0
    assert "DOGFOOD_TARGET must be" in result.stderr
    assert not (tmp_path / "state").exists()


def test_every_target_kind_is_accepted(tmp_path: Path):
    # Past the kind check the script stops at the missing installer image.
    for kind in ("blank", "foreign-gpt", "ext4", "xfs", "prior-install"):
        result = run_dogfood(tmp_path, DOGFOOD_TARGET=kind)
        assert result.returncode != 0
        assert "no bluefin-server-installer_<ver>.raw" in result.stderr, (kind, result.stderr)


def test_the_install_must_leave_only_the_esp_and_usr_slot_a():
    # Leftover partitions from what the disk held before would make first-boot
    # by-partlabel lookups ambiguous.
    assert "installed-slot-b=0 installed-parts=3" in DOGFOOD.read_text(encoding="utf-8")


def test_the_non_empty_disk_variants_are_documented_on_the_just_recipe():
    text = JUSTFILE.read_text(encoding="utf-8")
    recipe = text[: text.index("dogfood-installer NEXT=")]
    assert "DOGFOOD_TARGET=foreign-gpt|ext4|xfs|prior-install" in recipe.rsplit("\n\n", 1)[-1]


def test_prior_install_does_not_combine_with_an_update(tmp_path: Path):
    # Steps 5-6 are the reinstall or the update, not both.
    next_dir = tmp_path / "next"
    next_dir.mkdir()
    (next_dir / "bluefin-server-1.2.efi").touch()
    image = tmp_path / "img"
    image.mkdir()
    result = subprocess.run(
        ["bash", str(DOGFOOD), str(image), str(next_dir)],
        env={**os.environ, "DOGFOOD_STATE": str(tmp_path / "state"), "DOGFOOD_TARGET": "prior-install"},
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "does not combine with <next>" in result.stderr
