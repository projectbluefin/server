"""Invariant coverage for the target-disk partition layout.

``files/installer/repart.d/*.conf`` is the recipe ``systemd-repart`` follows when
the live installer partitions the *target* disk. Nothing in CI parses these
files today, so a typo in a ``Type=``, a ``CopyBlocks=`` source that no longer
matches the label the installer media stamps on its data partition, or a
partition going missing would only surface as a failed or silently
mis-partitioned install.

The layout is Flatcar's EFI-SYSTEM / USR-A / USR-B / OEM / ROOT, adopted in
projectbluefin/server#134. The ``Type=`` values for USR-A, USR-B, OEM and ROOT
are upstream GPT type GUIDs and must appear verbatim.

These tests are pure static checks: they read the shipped configs (plus the
installer element and the sysupdate transfer for cross-file consistency) and
assert the invariants the installer depends on. No BuildStream, no root, no
block devices.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPART_DIR = REPO_ROOT / "files" / "installer" / "repart.d"
ELEMENTS_DIR = REPO_ROOT / "elements"
ROOT_TRANSFER = REPO_ROOT / "files" / "os" / "sysupdate.d" / "50-root.transfer"

# Flatcar GPT type GUIDs, adopted verbatim by projectbluefin/server#134.
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
USR_GUID = "5dfbf5f4-2848-4bac-aa5e-0d9a20b745a6"
OEM_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ROOT_GUID = "3884dd41-8582-4404-b9a8-e9b84f2df50e"

# PARTLABELs the installer provisions on the target disk, in repart order.
EXPECTED_LABELS = ["EFI-SYSTEM", "USR-A", "USR-B", "OEM", "ROOT"]

SIZE_SUFFIXES = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def parse_size(value: str) -> int:
    """Parse a systemd size string (``500M``, ``1G``, ``4096``) into bytes."""
    match = re.fullmatch(r"(\d+)([KMGT]?)", value.strip())
    assert match, f"unparseable systemd size: {value!r}"
    number, suffix = match.groups()
    return int(number) * SIZE_SUFFIXES.get(suffix, 1)


def load_config(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=True)
    # systemd drop-ins are case-sensitive; configparser lowercases keys by default.
    parser.optionxform = str
    parser.read_string(path.read_text(encoding="utf-8"))
    return parser


def sysupdate_root_targets() -> list[str]:
    """Target-slot GPT labels from the ``[Target]`` section of 50-root.transfer.

    The transfer file carries a ``MatchPattern=`` in both ``[Source]`` (the
    release asset name) and ``[Target]`` (the partition labels); only the latter
    names partitions.
    """
    parser = configparser.ConfigParser(strict=True)
    parser.optionxform = str
    parser.read_string(ROOT_TRANSFER.read_text(encoding="utf-8"))
    assert parser.has_option("Target", "MatchPattern"), (
        f"{ROOT_TRANSFER.name} declares no [Target] MatchPattern"
    )
    return parser["Target"]["MatchPattern"].split()


def repart_files() -> list[Path]:
    return sorted(REPART_DIR.glob("*.conf"))


CONFIG_PATHS = repart_files()


def partitions() -> dict[str, dict[str, str]]:
    """Map ``10-esp.conf`` → its ``[Partition]`` section, for every config."""
    result: dict[str, dict[str, str]] = {}
    for path in CONFIG_PATHS:
        parser = load_config(path)
        result[path.name] = dict(parser["Partition"])
    return result


def test_repart_directory_is_populated():
    assert CONFIG_PATHS, f"no repart.d configs found under {REPART_DIR}"


@pytest.mark.parametrize("path", CONFIG_PATHS, ids=lambda p: p.name)
def test_config_parses_with_a_partition_section(path: Path):
    parser = load_config(path)
    assert parser.sections() == ["Partition"], (
        f"{path.name} must define exactly one [Partition] section, "
        f"got {parser.sections()}"
    )


@pytest.mark.parametrize("path", CONFIG_PATHS, ids=lambda p: p.name)
def test_config_filename_is_ordered_and_lowercase(path: Path):
    assert re.fullmatch(
        r"\d{2}-[a-z0-9-]+\.conf", path.name
    ), f"{path.name} must be NN-name.conf so systemd-repart orders it predictably"


def test_config_ordering_prefixes_are_unique():
    prefixes = [p.name[:2] for p in CONFIG_PATHS]
    assert len(prefixes) == len(set(prefixes)), (
        "two repart.d configs share an ordering prefix, so partition order "
        f"depends on the filename tiebreak: {prefixes}"
    )


def test_expected_partitions_are_present_exactly_once():
    labels = [
        section["Label"]
        for section in partitions().values()
        if "Label" in section
    ]
    assert sorted(labels) == sorted(EXPECTED_LABELS), (
        "the target layout must be exactly one each of EFI-SYSTEM, USR-A, "
        f"USR-B, OEM and ROOT partition, got {sorted(labels)}"
    )


@pytest.mark.parametrize(
    "name,section",
    sorted(partitions().items()),
    ids=[p.name for p in CONFIG_PATHS],
)
def test_size_bounds_are_consistent(name: str, section: dict[str, str]):
    minimum = section.get("SizeMinBytes")
    maximum = section.get("SizeMaxBytes")
    assert minimum, f"{name} must set SizeMinBytes so a too-small disk fails loudly"
    if maximum is not None:
        assert parse_size(minimum) <= parse_size(maximum), (
            f"{name}: SizeMinBytes={minimum} exceeds SizeMaxBytes={maximum}, "
            "systemd-repart would refuse the layout"
        )


def test_partition_labels_are_unique():
    labels = [
        section["Label"]
        for section in partitions().values()
        if "Label" in section
    ]
    assert len(labels) == len(set(labels)), (
        f"duplicate GPT partition labels would make Path=auto ambiguous: {labels}"
    )


def test_efi_system_is_vfat_and_bounded():
    esp = next(
        (s for s in partitions().values() if s.get("Label") == "EFI-SYSTEM"),
        None,
    )
    assert esp is not None, "EFI-SYSTEM partition missing"
    assert esp.get("Type") == "esp", "the EFI-SYSTEM partition must be an ESP"
    assert esp["Format"] == "vfat", "an ESP that is not vfat is unbootable by UEFI"
    assert parse_size(esp["SizeMinBytes"]) >= 100 * 1024**2, (
        "the ESP must be large enough for systemd-boot plus at least one UKI"
    )
    assert "SizeMaxBytes" in esp, "the ESP must be capped so it cannot eat the disk"


def test_usr_a_copies_blocks_from_a_label_the_installer_media_stamps():
    usr_a = next(
        (s for s in partitions().values() if s.get("Label") == "USR-A"),
        None,
    )
    assert usr_a is not None, "USR-A partition missing"
    assert usr_a["Type"] == USR_GUID, (
        "USR-A must carry Flatcar's usr type GUID verbatim"
    )
    copy_blocks = usr_a.get("CopyBlocks")
    assert copy_blocks, (
        "USR-A must CopyBlocks= the /usr DDI payload; without it the installed "
        "system has an empty /usr"
    )
    prefix = "/dev/disk/by-partlabel/"
    assert copy_blocks.startswith(prefix), (
        f"CopyBlocks={copy_blocks} should address the installer media by "
        "partition label, not by an unstable device node"
    )
    partlabel = copy_blocks[len(prefix):]
    stamped = any(
        re.search(rf"^\s*Label={re.escape(partlabel)}\s*$", text, re.MULTILINE)
        for text in (
            path.read_text(encoding="utf-8")
            for path in ELEMENTS_DIR.rglob("*.bst")
        )
    )
    assert stamped, (
        f"no element stamps Label={partlabel} on the installer media data "
        "partition, so CopyBlocks= would resolve to nothing at install time"
    )


def test_usr_b_exists_and_is_empty():
    usr_b = next(
        (s for s in partitions().values() if s.get("Label") == "USR-B"),
        None,
    )
    assert usr_b is not None, "USR-B partition missing"
    assert usr_b["Type"] == USR_GUID, (
        "USR-B must carry Flatcar's usr type GUID verbatim so the kernel "
        "recognises the USR-A/USR-B pair"
    )
    assert "CopyBlocks" not in usr_b, (
        "USR-B is the rollback slot and must stay empty, not a copy of the DDI"
    )
    assert "CopyFiles" not in usr_b, "USR-B must be empty, not seeded from files"
    assert "Format" not in usr_b, "USR-B must be left unformatted (empty)"


def test_oem_is_labelled_ext4():
    oem = next(
        (s for s in partitions().values() if s.get("Label") == "OEM"),
        None,
    )
    assert oem is not None, "OEM partition missing"
    assert oem["Type"] == OEM_GUID, (
        "OEM must carry Flatcar's OEM type GUID verbatim"
    )
    assert oem.get("Format") == "ext4", "OEM must be ext4"
    # Stage 2 waits on dev-disk-by-label-OEM.device: the match is on the
    # filesystem LABEL, so Label=OEM must also be the filesystem label.
    assert oem.get("Label") == "OEM", (
        "OEM must be formatted with filesystem label OEM or stage 2 never finds it"
    )


def test_root_grows_and_is_bounded_below_oem():
    root = next(
        (s for s in partitions().values() if s.get("Label") == "ROOT"),
        None,
    )
    assert root is not None, "ROOT partition missing"
    assert root["Type"] == ROOT_GUID, (
        "ROOT must carry Flatcar's root type GUID verbatim"
    )
    assert root.get("GrowFileSystem") == "yes", (
        "the ROOT partition must grow to fill the disk after the other slots"
    )
    assert "SizeMaxBytes" not in root, (
        "ROOT is the tail partition and must grow into all remaining space"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Follow-on: 50-root.transfer still targets the legacy "
        "bluefin-server-root-<ver>_a/_b labels, but the Flatcar layout (project"
        "bluefin/server#134) provisions USR-A/USR-B instead. Wiring the transfer "
        "to the real /usr slots and retiring this xfail is a later ticket, so "
        "the label-match assertion is expected to fail until then."
    ),
)
def test_root_partition_label_is_matched_by_the_sysupdate_root_transfer():
    root = next(
        (s for s in partitions().values() if s.get("Label") == "ROOT"),
        None,
    )
    assert root is not None
    targets = sysupdate_root_targets()
    prefix, _, suffix = targets[0].partition("@v")
    assert root["Label"].startswith(prefix) and root["Label"].endswith(suffix.lstrip("_")), (
        f"the installed root label {root['Label']!r} is not matched by "
        f"sysupdate target pattern {targets[0]}; OTA updates would find no slot"
    )
