"""Invariants of the installed-disk partition layout (files/os/repart.d).

The same definitions serve three consumers:

* ``systemd-sysinstall`` (via the UUID-pinned copy bluefin-server-boot.bst
  exports) writes the ESP and usr slot A from the running image,
* the installed system's initrd ``systemd-repart`` (reading
  /sysusr/usr/lib/repart.d) creates slot B and root on first boot,
* ``systemd-sysupdate`` later fills slot B, matching the labels below.

Pure static checks: no BuildStream, no block devices.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from _systemd import SystemdFile

REPO_ROOT = Path(__file__).resolve().parents[2]
REPART_DIR = REPO_ROOT / "files" / "os" / "repart.d"
SYSUPDATE_DIR = REPO_ROOT / "files" / "os" / "sysupdate.d"
BOOT_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-boot.bst"

EXPECTED = {
    "10-esp.conf": "esp",
    "20-usr-a.conf": "usr",
    "21-usr-verity-a.conf": "usr-verity",
    "30-usr-b.conf": "usr",
    "31-usr-verity-b.conf": "usr-verity",
    "50-root.conf": "root",
}


def load(path: Path) -> dict[str, str]:
    return {key: values[-1] for key, values in SystemdFile(path).sections["Partition"].items()}


def transfer_target(name: str) -> dict[str, str]:
    return {key: values[-1] for key, values in SystemdFile(SYSUPDATE_DIR / name).sections["Target"].items()}


def test_layout_files_and_types():
    found = {p.name: load(p)["Type"] for p in sorted(REPART_DIR.glob("*.conf"))}
    assert found == EXPECTED


@pytest.mark.parametrize(
    "a,b",
    [("20-usr-a.conf", "30-usr-b.conf"), ("21-usr-verity-a.conf", "31-usr-verity-b.conf")],
)
def test_ab_slots_have_identical_fixed_sizes(a: str, b: str):
    slot_a, slot_b = load(REPART_DIR / a), load(REPART_DIR / b)
    for slot in (slot_a, slot_b):
        assert slot["SizeMinBytes"] == slot["SizeMaxBytes"], "slots must not grow"
    assert slot_a["SizeMinBytes"] == slot_b["SizeMinBytes"]


def test_slot_a_is_copied_from_the_running_image():
    for name in ("20-usr-a.conf", "21-usr-verity-a.conf"):
        assert load(REPART_DIR / name)["CopyBlocks"] == "auto"


def test_slot_b_starts_empty_for_sysupdate():
    for name in ("30-usr-b.conf", "31-usr-verity-b.conf"):
        part = load(REPART_DIR / name)
        assert part["Label"] == "_empty"
        assert "CopyBlocks" not in part


@pytest.mark.parametrize(
    "repart,transfer",
    [("20-usr-a.conf", "10-usr.transfer"), ("21-usr-verity-a.conf", "11-usr-verity.transfer")],
)
def test_slot_labels_match_the_sysupdate_target_pattern(repart: str, transfer: str):
    part = load(REPART_DIR / repart)
    target = transfer_target(transfer)
    assert part["Label"].replace("%A", "@v") == target["MatchPattern"]
    assert part["Type"] == target["MatchPartitionType"]


def test_root_is_persistent_xfs_with_mount_points():
    root = load(REPART_DIR / "50-root.conf")
    assert root["Format"] == "xfs"
    assert root["FactoryReset"] == "yes"
    directories = SystemdFile(REPART_DIR / "50-root.conf").words("Partition", "MakeDirectories")
    for directory in ("/usr", "/etc", "/efi", "/var"):
        assert directory in directories


def test_boot_element_pins_slot_a_uuids_for_sysinstall():
    text = BOOT_ELEMENT.read_text(encoding="utf-8")
    assert "cp /repart/usr/lib/repart.d/*.conf" in text
    assert '>> "${d}/20-usr-a.conf"' in text
    assert '>> "${d}/21-usr-verity-a.conf"' in text


def test_netboot_does_not_automount_the_in_ram_esp():
    # On a diskless boot the gpt-auto generator finds the ESP through the
    # block device backing /usr. After systemd-sysext merges an extension
    # /usr is an overlay, the regenerated boot.mount disappears, and the
    # orphaned boot.automount hangs systemd-boot-update.service (seen on
    # legacy BIOS netboot, where no EFI loader variable names the ESP).
    netboot = BOOT_ELEMENT.read_text(encoding="utf-8").split("netboot-cmdline:")[1]
    netboot = netboot.split("disk-cmdline:")[0]
    assert "systemd.mask=boot.automount" in netboot
    assert "systemd.mask=boot.mount" in netboot
