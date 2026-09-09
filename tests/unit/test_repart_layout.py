"""Invariant coverage for the target-disk partition layout.

``files/installer/repart.d/*.conf`` is the recipe ``systemd-repart`` follows when
the live installer partitions the *target* disk. Nothing in CI parses these
files today, so a typo in a ``Type=``, a ``CopyBlocks=`` source that no longer
matches the label the installer media stamps on its data partition, or an
``esp``/``root``/``var`` slot going missing would only surface as a failed or
silently mis-partitioned install.

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


def test_expected_partition_types_are_present_exactly_once():
    types = [section["Type"] for section in partitions().values()]
    assert sorted(types) == ["esp", "root", "var"], (
        "the target layout must be exactly one esp, one root and one var "
        f"partition, got {sorted(types)}"
    )


@pytest.mark.parametrize("name,section", sorted(partitions().items()))
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


def test_esp_is_vfat_and_bounded():
    esp = next(s for s in partitions().values() if s["Type"] == "esp")
    assert esp["Format"] == "vfat", "an ESP that is not vfat is unbootable by UEFI"
    assert parse_size(esp["SizeMinBytes"]) >= 100 * 1024**2, (
        "the ESP must be large enough for systemd-boot plus at least one UKI"
    )
    assert "SizeMaxBytes" in esp, "the ESP must be capped so it cannot eat the disk"


def test_root_slot_copies_blocks_from_a_label_the_installer_media_stamps():
    root = next(s for s in partitions().values() if s["Type"] == "root")
    copy_blocks = root.get("CopyBlocks")
    assert copy_blocks, (
        "the root partition must CopyBlocks= the DDI payload; without it the "
        "installed system has an empty root filesystem"
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


def test_root_slot_grows_and_is_bounded_below_the_var_partition():
    root = next(s for s in partitions().values() if s["Type"] == "root")
    assert root.get("GrowFileSystem") == "yes", (
        "the root filesystem must grow to its partition, the DDI payload is "
        "smaller than SizeMinBytes"
    )
    assert "SizeMaxBytes" in root, (
        "the root slot must be capped, otherwise /var gets no space on small disks"
    )


def test_var_is_a_growing_xfs_tail():
    var = next(s for s in partitions().values() if s["Type"] == "var")
    assert var["Format"] == "xfs"
    # FactoryReset=yes must NOT be set on the installer var partition:
    # systemd-sysinstall hardcodes deferPartitionsFactoryReset=true via
    # Varlink io.systemd.Repart.Run, causing it to defer creating /var.
    assert "FactoryReset" not in var, (
        "FactoryReset must not be set on installer var partition or "
        "systemd-sysinstall will defer creating it"
    )
    assert var["GrowFileSystem"] == "yes"
    assert "SizeMaxBytes" not in var, (
        "/var is the tail partition and must grow into all remaining space"
    )


def test_var_seeds_the_offline_k0s_sysext():
    var = next(s for s in partitions().values() if s["Type"] == "var")
    assert var["CopyFiles"] == "/k0s.raw:/lib/k0s/k0s.raw"


def test_root_partition_label_is_matched_by_the_sysupdate_root_transfer():
    root = next(s for s in partitions().values() if s["Type"] == "root")
    targets = sysupdate_root_targets()
    assert root["Label"] in targets, (
        f"the installed root label {root['Label']!r} is not among the "
        f"sysupdate target labels {targets}; OTA updates would find no slot"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Known gap, tracked in docs/MVP_1_0_READINESS.md: 50-root.transfer names "
        "root-a and root-b, but the installer provisions only root-a, so "
        "systemd-sysupdate has no inactive slot to stage into and no atomic "
        "rollback path. When root-b is added this test XPASSes and must be "
        "un-xfailed."
    ),
)
def test_every_sysupdate_root_target_is_provisioned_by_the_installer():
    targets = set(sysupdate_root_targets())
    provisioned = {
        section["Label"]
        for section in partitions().values()
        if section["Type"] == "root"
    }
    assert targets <= provisioned, (
        f"sysupdate targets {sorted(targets - provisioned)} are never created "
        "by files/installer/repart.d/"
    )
