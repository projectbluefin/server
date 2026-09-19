"""Invariant coverage for the target-disk partition layout.

``files/installer/repart.d/*.conf`` is the recipe ``systemd-repart`` follows when
the live installer partitions the *target* disk. Nothing in CI parses these
files today, so a typo in a ``Type=``, a ``CopyBlocks=`` source that no longer
matches the label the installer media stamps on its data partition, or a
partition going missing would only surface as a failed or silently
mis-partitioned install.

The layout is Flatcar's EFI-SYSTEM / USR-A / USR-B / OEM / ROOT, adopted by
projectbluefin/server#134. The ``Type=`` values for USR-A, USR-B, OEM and ROOT
are upstream GPT type GUIDs and must appear verbatim. ROOT's GUID is *not* a
Discoverable Partitions Specification type, so the target UKI cmdline must
carry ``root=`` explicitly — also pinned here, per the review that rejected
the first layout PR: the suite must catch a layout that boots with no way to
find its root filesystem.

These tests are pure static checks: they read the shipped configs (plus the
installer element, the DDI element and the sysupdate transfer for cross-file
consistency) and assert the invariants the installer depends on. No
BuildStream, no root, no block devices.
"""

from __future__ import annotations

import configparser
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
REPART_DIR = REPO_ROOT / "files" / "installer" / "repart.d"
ELEMENTS_DIR = REPO_ROOT / "elements"
OS_FILES_DIR = REPO_ROOT / "files" / "os"
INSTALLER_ELEMENT = ELEMENTS_DIR / "oci" / "bluefin-server-installer.bst"
DDI_ELEMENT = ELEMENTS_DIR / "oci" / "bluefin-server-ddi.bst"
ROOT_TRANSFER = REPO_ROOT / "files" / "os" / "sysupdate.d" / "50-root.transfer"

# Flatcar GPT type GUIDs, adopted verbatim by projectbluefin/server#134.
ESP_GUID = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b"
USR_GUID = "5dfbf5f4-2848-4bac-aa5e-0d9a20b745a6"
OEM_GUID = "0fc63daf-8483-4772-8e79-3d69d8477de4"
ROOT_GUID = "3884dd41-8582-4404-b9a8-e9b84f2df50e"

# PARTLABELs the installer provisions on the target disk, in repart order.
EXPECTED_LABELS = ["EFI-SYSTEM", "USR-A", "USR-B", "OEM", "ROOT"]

# Kernel parameters that place the root filesystem and the read-only /usr.
TARGET_CMDLINE_TOKENS = [
    "root=PARTLABEL=ROOT",
    "mount.usr=PARTLABEL=USR-A",
    "mount.usrfstype=xfs",
    "mount.usrflags=ro",
]

SIZE_SUFFIXES = {"K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}


def parse_size(value: str) -> int:
    """Parse a systemd size string (``500M``, ``1G``, ``4096``) into bytes."""
    match = re.fullmatch(r"(\d+)([KMGT]?)", value.strip())
    assert match, f"unparseable systemd size: {value!r}"
    number, suffix = match.groups()
    return int(number) * SIZE_SUFFIXES.get(suffix, 1)


def load_sections(path: Path) -> dict[str, dict[str, list[str]]]:
    """Parse a systemd-style config into sections of key → repeated values.

    ``repart.d`` allows repeated keys (``CopyFiles=``), which configparser
    cannot represent, so the section grammar is parsed directly: comments are
    stripped per-line, section headers delimit scope, and every ``key=value``
    line appends to its key's list.
    """
    sections: dict[str, dict[str, list[str]]] = {}
    current: dict[str, list[str]] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = sections.setdefault(line[1:-1], {})
            continue
        if current is None:
            continue
        key, _, value = line.partition("=")
        current.setdefault(key.strip(), []).append(value.strip())
    return sections


def load_config(path: Path) -> configparser.ConfigParser:
    """Plain configparser loader for transfer files (no repeated keys)."""
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
    parser = load_config(ROOT_TRANSFER)
    assert parser.has_option("Target", "MatchPattern"), (
        f"{ROOT_TRANSFER.name} declares no [Target] MatchPattern"
    )
    return parser["Target"]["MatchPattern"].split()


def repart_files() -> list[Path]:
    return sorted(REPART_DIR.glob("*.conf"))


CONFIG_PATHS = repart_files()


def partitions() -> dict[str, dict[str, list[str]]]:
    """Map ``10-esp.conf`` → its ``[Partition]`` section, for every config."""
    result: dict[str, dict[str, list[str]]] = {}
    for path in CONFIG_PATHS:
        result[path.name] = load_sections(path)["Partition"]
    return result


def by_label(label: str) -> dict[str, list[str]]:
    """The [Partition] section of the config labelled ``label``."""
    matches = [s for s in partitions().values() if s.get("Label") == [label]]
    assert len(matches) == 1, f"expected exactly one {label} partition"
    return matches[0]


def single(section: dict[str, list[str]], key: str) -> str | None:
    """The sole value for ``key`` in a partition section, or None if unset."""
    values = section.get(key)
    if values is None:
        return None
    assert len(values) == 1, f"{key}= is set more than once: {values}"
    return values[0]


def installer_text() -> str:
    return INSTALLER_ELEMENT.read_text(encoding="utf-8")


def target_uki_cmdlines() -> list[str]:
    """Kernel cmdline strings baked into the target OS UKI.

    The target cmdline is set twice on purpose (dracut ``--kernel-cmdline`` and
    ukify ``--cmdline=`` must agree); the installer's own UKI cmdline is
    excluded because it boots the live installer environment, not the target.
    """
    text = installer_text()
    candidates = re.findall(r'--cmdline="([^"]*)"', text) + re.findall(
        r"--kernel-cmdline \"([^\"]*)\"", text
    )
    return [c for c in candidates if "mount.usr=" in c]


def test_repart_directory_is_populated():
    assert CONFIG_PATHS, f"no repart.d configs found under {REPART_DIR}"


@pytest.mark.parametrize("path", CONFIG_PATHS, ids=lambda p: p.name)
def test_config_parses_with_a_partition_section(path: Path):
    sections = load_sections(path)
    assert list(sections) == ["Partition"], (
        f"{path.name} must define exactly one [Partition] section, "
        f"got {list(sections)}"
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
        section["Label"][0]
        for section in partitions().values()
        if "Label" in section
    ]
    assert sorted(labels) == sorted(EXPECTED_LABELS), (
        "the target layout must be exactly one each of EFI-SYSTEM, USR-A, "
        f"USR-B, OEM and ROOT partition, got {sorted(labels)}"
    )


@pytest.mark.parametrize("name,section", sorted(partitions().items()))
def test_size_bounds_are_consistent(name: str, section: dict[str, list[str]]):
    minimum = single(section, "SizeMinBytes")
    maximum = single(section, "SizeMaxBytes")
    assert minimum, f"{name} must set SizeMinBytes so a too-small disk fails loudly"
    if maximum is not None:
        assert parse_size(minimum) <= parse_size(maximum), (
            f"{name}: SizeMinBytes={minimum} exceeds SizeMaxBytes={maximum}, "
            "systemd-repart would refuse the layout"
        )


def test_partition_labels_are_unique():
    labels = [
        section["Label"][0]
        for section in partitions().values()
        if "Label" in section
    ]
    assert len(labels) == len(set(labels)), (
        f"duplicate GPT partition labels would make Path=auto ambiguous: {labels}"
    )


def test_efi_system_is_vfat_and_bounded():
    esp = by_label("EFI-SYSTEM")
    assert single(esp, "Type") == "esp", (
        f"the EFI-SYSTEM partition must be an ESP (type GUID {ESP_GUID})"
    )
    assert single(esp, "Format") == "vfat", (
        "an ESP that is not vfat is unbootable by UEFI"
    )
    assert parse_size(single(esp, "SizeMinBytes")) >= 100 * 1024**2, (
        "the ESP must be large enough for systemd-boot plus at least one UKI"
    )
    assert "SizeMaxBytes" in esp, "the ESP must be capped so it cannot eat the disk"


def test_usr_a_copies_blocks_from_a_label_the_installer_media_stamps():
    usr_a = by_label("USR-A")
    assert single(usr_a, "Type") == USR_GUID, (
        "USR-A must carry Flatcar's usr type GUID verbatim"
    )
    copy_blocks = single(usr_a, "CopyBlocks")
    assert copy_blocks, (
        "USR-A must CopyBlocks= the DDI /usr payload; without it the installed "
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
    usr_b = by_label("USR-B")
    assert single(usr_b, "Type") == USR_GUID, (
        "USR-B must carry Flatcar's usr type GUID verbatim so the kernel "
        "recognises the USR-A/USR-B pair"
    )
    assert "CopyBlocks" not in usr_b, (
        "USR-B is the rollback slot and must stay empty, not a copy of the DDI"
    )
    assert "CopyFiles" not in usr_b, "USR-B must be empty, not seeded from files"
    assert "Format" not in usr_b, "USR-B must be left unformatted (empty)"


def test_oem_is_labelled_ext4():
    oem = by_label("OEM")
    assert single(oem, "Type") == OEM_GUID, (
        "OEM must carry Flatcar's OEM type GUID verbatim"
    )
    assert single(oem, "Format") == "ext4", "OEM must be ext4"
    # Flatcar's stage 2 waits on dev-disk-by-label-OEM.device: the match is on
    # the filesystem LABEL, so Label=OEM must also be the filesystem label.
    assert single(oem, "Label") == "OEM", (
        "OEM must be formatted with filesystem label OEM or stage 2 never finds it"
    )


def test_root_carries_flatcars_root_guid_and_grows():
    root = by_label("ROOT")
    assert single(root, "Type") == ROOT_GUID, (
        "ROOT must carry Flatcar's root type GUID verbatim"
    )
    assert single(root, "Format") == "ext4", (
        "ROOT must be formatted at install time: the target boots this "
        "partition as its root filesystem, an unformatted ROOT is unbootable"
    )
    assert single(root, "GrowFileSystem") == "yes", (
        "the ROOT partition must grow to fill the disk after the other slots"
    )
    assert "SizeMaxBytes" not in root, (
        "ROOT is the tail partition and must grow into all remaining space"
    )


def test_root_seeds_the_offline_k0s_sysext():
    root = by_label("ROOT")
    assert "/k0s.raw:/var/lib/k0s/k0s.raw" in root.get("CopyFiles", []), (
        "the offline k0s sysext must be seeded into ROOT at the path "
        "k0s-first-boot-fetch.service checks, or offline installs cannot "
        "enable Kubernetes"
    )


def test_root_seeds_the_target_etc_from_the_installer_assembly():
    root = by_label("ROOT")
    assert "/usr/lib/bluefin-server/etc-seed:/etc" in root.get("CopyFiles", []), (
        "ROOT must be seeded with /etc from the installer-assembled "
        "etc-seed: the DDI payload is /usr-only, so without it the installed "
        "system has no /etc (no login, no CA bundle, no unit masks)"
    )
    # The seed must actually be assembled by the installer element.
    assert "/usr/lib/bluefin-server/etc-seed" in installer_text(), (
        "bluefin-server-installer.bst must assemble the /etc seed at "
        "/usr/lib/bluefin-server/etc-seed for CopyFiles= to unpack"
    )


def test_target_uki_cmdline_carries_root_and_usr_placement():
    """ROOT's type GUID is not DPS-discoverable, so root= must be explicit.

    This is the boot-discovery assertion the #134 review asked for: a layout
    that drops the Discoverable Partitions root type and also lacks ``root=``
    on the kernel cmdline leaves the installed system no way to mount its root.
    """
    cmdlines = target_uki_cmdlines()
    assert cmdlines, (
        "no target UKI cmdline found in bluefin-server-installer.bst; the "
        "cmdline must place root (root=PARTLABEL=ROOT) and /usr "
        "(mount.usr=PARTLABEL=USR-A mount.usrfstype=xfs mount.usrflags=ro)"
    )
    for cmdline in cmdlines:
        for token in TARGET_CMDLINE_TOKENS:
            assert token in cmdline, (
                f"the target UKI cmdline is missing {token!r}: with the Flatcar "
                "type GUIDs, neither systemd-gpt-auto-generator nor the kernel "
                "can discover ROOT on their own"
            )
    # The live installer cmdline boots the initrd-only environment and must
    # not carry target placement parameters.
    installer_cmdlines = re.findall(r'--cmdline="([^"]*)"', installer_text())
    live = [c for c in installer_cmdlines if "system-install.target" in c]
    assert live, "the installer UKI cmdline (system-install.target) went missing"
    for cmdline in live:
        assert "mount.usr=" not in cmdline and "root=PARTLABEL=" not in cmdline, (
            "the installer UKI boots the live environment from its initrd; "
            "target placement parameters must stay on the target UKI only"
        )


def test_target_usr_fstype_matches_the_ddi_filesystem():
    ddi_text = DDI_ELEMENT.read_text(encoding="utf-8")
    assert "mkfs.xfs" in ddi_text, (
        "the DDI payload must be built as XFS: the target cmdline mounts "
        "mount.usrfstype=xfs, a mismatch leaves the target unable to mount /usr"
    )


def test_no_shipped_unit_requires_the_removed_var_partition():
    """The var partition is gone (#134): nothing may still name it.

    var.mount pointed at /dev/disk/by-partlabel/var and was preset-enabled;
    with no producer the unit fails, local-fs.target fails, and the box drops
    to emergency mode. The unit and its preset must not merely be unprovisioned
    but actually removed, and no shipped config may reference the label again.
    """
    assert not (OS_FILES_DIR / "systemd" / "system" / "var.mount").exists(), (
        "var.mount must be removed: the Flatcar layout has no var partition"
    )
    assert not (
        OS_FILES_DIR / "systemd" / "system-preset" / "zz-enable-var-mount.preset"
    ).exists(), "the preset enabling var.mount must be removed with it"
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for path in list(OS_FILES_DIR.rglob("*")) + [DDI_ELEMENT]
        if path.is_file()
        and "/dev/disk/by-partlabel/var"
        in path.read_text(encoding="utf-8", errors="replace")
    ]
    assert not offenders, (
        f"files still reference the removed var partition: {offenders}"
    )


def test_repart_defines_no_var_partition():
    types = [single(section, "Type") for section in partitions().values()]
    assert "var" not in types, (
        "the Flatcar layout has no var partition; /var lives on the writable "
        f"ROOT (got types {types})"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Follow-on: 50-root.transfer still targets the legacy "
        "bluefin-server-root-<ver>_a/_b labels, but the Flatcar layout "
        "(projectbluefin/server#134) provisions USR-A/USR-B instead. Wiring "
        "the transfer to the real /usr slots and retiring this xfail is the "
        "sysupdate follow-on ticket, so the label-match assertion is expected "
        "to fail until then. It also still names two slots; USR-B is "
        "provisioned empty, so no atomic rollback path exists until the "
        "sysupdate wiring lands."
    ),
)
def test_root_partition_label_is_matched_by_the_sysupdate_root_transfer():
    targets = sysupdate_root_targets()
    prefix, _, suffix = targets[0].partition("@v")
    root = by_label("ROOT")
    assert single(root, "Label").startswith(prefix) and single(root, "Label").endswith(
        suffix.lstrip("_")
    ), (
        f"the installed root label {single(root, 'Label')!r} is not matched by "
        f"sysupdate target pattern {targets[0]}; OTA updates would find no slot"
    )