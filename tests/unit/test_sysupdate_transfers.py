"""Unit coverage for the OS and component sysupdate transfer definitions.

``tests/unit/test_repart_layout.py`` already pins ``50-root.transfer`` against
the installer repart config. The other two OTA transfer definitions —
``60-uki.transfer`` (the boot UKI) and ``70-k0s.transfer`` (the k0s sysext) —
have no coverage at all, and neither does the source-side artifact naming that
systemd-sysupdate matches against.

These tests assert the drift-prone contracts:

* every transfer parses and carries ``[Transfer]``/``[Source]``/``[Target]``
* every source pulls from this repo's own release feed over https
* every source ``MatchPattern`` corresponds to an artifact name that some
  element under ``elements/`` actually emits (``bluefin-server-ddi-<v>.raw.zst``,
  ``bluefin-server-<v>.efi``, ``k0s-<v>.raw.zst``)
* each component sysext on its own version axis (k0s, the NVIDIA Container
  Toolkit) is staged outside ``/var/lib/extensions`` behind a stable
  ``CurrentSymlink`` whose name its ``extension-release`` (``ID=_any``) merges
"""

import configparser
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSUPDATE_DIR = REPO_ROOT / "files" / "os" / "sysupdate.d"
K0S_SYSUPDATE_DIR = REPO_ROOT / "files" / "os" / "sysupdate.k0s.d"
CTK_SYSUPDATE_DIR = REPO_ROOT / "files" / "os" / "sysupdate.nvidia-container-toolkit.d"
ELEMENTS_DIR = REPO_ROOT / "elements"

# Sysexts on their own version axis: one sysupdate component each, staged in
# a state directory and merged through a stable symlink by an opt-in unit.
COMPONENTS = {
    "k0s": {
        "transfer": K0S_SYSUPDATE_DIR / "70-k0s.transfer",
        "state": "/var/lib/k0s",
        "release": REPO_ROOT / "files" / "k0s" / "sysext" / "extension-release.k0s",
    },
    "nvidia-container-toolkit": {
        "transfer": CTK_SYSUPDATE_DIR / "71-nvidia-container-toolkit.transfer",
        "state": "/var/lib/nvidia-container-toolkit",
        "release": REPO_ROOT
        / "files"
        / "nvidia-container-toolkit"
        / "sysext"
        / "extension-release.nvidia-container-toolkit",
    },
}

RELEASE_FEED = "https://github.com/projectbluefin/server/releases/latest/download/"


def transfer_paths() -> list[Path]:
    return sorted(
        (
            *SYSUPDATE_DIR.glob("*.transfer"),
            *K0S_SYSUPDATE_DIR.glob("*.transfer"),
            *CTK_SYSUPDATE_DIR.glob("*.transfer"),
        )
    )


def load_transfer(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    # systemd keys are case sensitive; configparser lowercases them by default.
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


def element_texts() -> str:
    """Every element definition concatenated, for artifact-name lookups.

    Sysext elements name their image in ``sysext-image:`` and
    ``include/sysext.yml`` writes ``%{sysext-image}.raw``; spell that out.
    """
    text = "\n".join(
        p.read_text() for p in sorted(ELEMENTS_DIR.rglob("*.bst"))
    )
    images = re.findall(r'^\s*sysext-image:\s*"([^"]+)"', text, re.MULTILINE)
    return "\n".join([text, *(f"{image}.raw" for image in images)])


def split_match_pattern(pattern: str) -> tuple[str, str]:
    """Return the literal ``(prefix, suffix)`` around sysupdate's ``@v`` token."""
    assert "@v" in pattern, f"MatchPattern {pattern!r} carries no @v version token"
    prefix, _, suffix = pattern.partition("@v")
    return prefix, suffix


def test_sysupdate_directories_are_populated():
    generic = sorted(p.name for p in SYSUPDATE_DIR.glob("*.transfer"))
    k0s = sorted(p.name for p in K0S_SYSUPDATE_DIR.glob("*.transfer"))
    assert generic == [
        "10-usr.transfer",
        "11-usr-verity.transfer",
        "20-uki.transfer",
        "30-zfs.transfer",
        "31-kubestellar.transfer",
        "32-kubeadm.transfer",
        "33-nvidia-open-595.transfer",
    ]
    assert k0s == ["70-k0s.transfer"]
    ctk = sorted(p.name for p in CTK_SYSUPDATE_DIR.glob("*.transfer"))
    assert ctk == ["71-nvidia-container-toolkit.transfer"]


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_transfer_has_the_three_required_sections(path: Path):
    parser = load_transfer(path)
    for section in ("Transfer", "Source", "Target"):
        assert parser.has_section(section), f"{path.name} is missing [{section}]"


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_transfer_filename_is_ordered_and_lowercase(path: Path):
    assert re.fullmatch(
        r"[0-9]{2}-[a-z0-9-]+\.transfer", path.name
    ), f"{path.name} must be NN-lowercase-name.transfer so ordering is explicit"


def test_transfer_ordering_prefixes_are_unique():
    prefixes = [p.name.split("-", 1)[0] for p in transfer_paths()]
    assert len(prefixes) == len(set(prefixes)), (
        f"duplicate sysupdate ordering prefixes {prefixes}; systemd-sysupdate "
        "applies transfers in filename order and ties are undefined"
    )


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_source_pulls_from_this_repo_release_feed_over_https(path: Path):
    source = load_transfer(path)["Source"]
    assert source.get("Type") == "url-file", (
        f"{path.name} [Source] Type is {source.get('Type')!r}; OTA payloads are "
        "fetched as release files"
    )
    assert source.get("Path") == RELEASE_FEED, (
        f"{path.name} [Source] Path is {source.get('Path')!r}, not {RELEASE_FEED!r}; "
        "updates would be fetched from an unintended origin"
    )


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_source_match_pattern_is_versioned(path: Path):
    pattern = load_transfer(path)["Source"].get("MatchPattern", "")
    assert pattern, f"{path.name} [Source] has no MatchPattern"
    prefix, suffix = split_match_pattern(pattern)
    assert prefix and suffix, (
        f"{path.name} MatchPattern {pattern!r} must have literal text on both "
        "sides of @v or it will match unrelated release assets"
    )


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_every_source_artifact_is_produced_by_an_element(path: Path):
    """The release asset a transfer downloads must be one the build emits.

    Renaming an artifact in ``elements/oci/*.bst`` without updating the matching
    transfer silently breaks OTA: sysupdate finds no candidate and reports the
    system as up to date forever. ``@u`` (partition UUID) is filled in by the
    element at build time, so only the literal text around it is checked.
    """
    prefix, suffix = split_match_pattern(
        load_transfer(path)["Source"]["MatchPattern"]
    )
    tail = suffix.split("@u", 1)[-1].removesuffix(".zst")
    produced = re.compile(
        re.escape(prefix) + r"%\{[a-z0-9-]+\}" + r"[^\n]*?" + re.escape(tail)
    )
    assert produced.search(element_texts()), (
        f"{path.name} expects release asset {prefix}<version>{suffix}, but no "
        f"element under {ELEMENTS_DIR} emits a file named that way"
    )


def test_uki_transfer_installs_into_boot_efi_linux_with_boot_counting():
    target = load_transfer(SYSUPDATE_DIR / "20-uki.transfer")["Target"]
    assert target.get("Type") == "regular-file"
    assert target.get("Path") == "/EFI/Linux"
    assert target.get("PathRelativeTo") == "boot", (
        "systemd-boot discovers Type #2 UKIs under $BOOT/EFI/Linux"
    )
    assert "+@l-@d" in target.get("MatchPattern", ""), "boot counting needs @l/@d"
    assert target.get("TriesLeft") == "3"
    assert "Mode" not in target, (
        "a read-only mode sets the FAT read-only attribute and systemd-boot can "
        "no longer rename the file to count boots"
    )


def test_uki_source_name_is_one_of_the_target_names():
    parser = load_transfer(SYSUPDATE_DIR / "20-uki.transfer")
    source = parser["Source"]["MatchPattern"]
    assert source in parser["Target"]["MatchPattern"].split(), (
        "sysupdate correlates installed and available UKIs by name"
    )
    assert source.startswith("bluefin-server-"), (
        "bootctl writes 'default bluefin-server-*' to loader.conf; an updated UKI "
        "outside that glob would never become the default entry"
    )


@pytest.mark.parametrize("name", ["10-usr.transfer", "11-usr-verity.transfer"])
def test_usr_transfers_carry_the_verity_partition_uuid(name: str):
    source = load_transfer(SYSUPDATE_DIR / name)["Source"]["MatchPattern"]
    assert "@u" in source, (
        "the partition UUID must come from the asset name: dm-verity finds usr "
        "partitions by UUIDs derived from usrhash"
    )


@pytest.mark.parametrize("name", sorted(COMPONENTS))
def test_component_sysext_transfer_stages_outside_the_extension_directories(name: str):
    component = COMPONENTS[name]
    target = load_transfer(component["transfer"])["Target"]
    assert target.get("Type") == "regular-file", (
        f"the {name} sysext is delivered as a decompressed regular file"
    )
    assert target.get("Path") == component["state"], (
        f"{name} sysext target path is {target.get('Path')!r}; the persistent "
        "staging path must remain outside systemd-sysext's early scan, where "
        "two versions of an ID=_any image would both merge"
    )
    assert target.get("Mode") == "0644", (
        f"{name} sysext mode is {target.get('Mode')!r}; the image must be readable "
        "by systemd-sysext at merge time"
    )


@pytest.mark.parametrize("name", sorted(COMPONENTS))
def test_component_sysext_transfer_maintains_a_stable_current_symlink(name: str):
    target = load_transfer(COMPONENTS[name]["transfer"])["Target"]
    symlink = target.get("CurrentSymlink")
    assert symlink == f"{name}.raw", (
        f"CurrentSymlink is {symlink!r}; the boot activation unit requires a "
        f"stable filename, so a version bump otherwise stops merging {name}"
    )
    prefix, suffix = split_match_pattern(target["MatchPattern"])
    assert symlink == f"{prefix.rstrip('-')}{suffix}", (
        f"CurrentSymlink {symlink!r} does not follow the versioned target name "
        f"{target['MatchPattern']!r}"
    )


@pytest.mark.parametrize("name", sorted(COMPONENTS))
def test_component_sysext_transfer_decompresses_the_release_asset(name: str):
    parser = load_transfer(COMPONENTS[name]["transfer"])
    source = parser["Source"]["MatchPattern"]
    target = parser["Target"]["MatchPattern"]
    assert source.endswith(".raw.zst"), f"{name} release asset {source!r} is not zstd"
    assert target == source.removesuffix(".zst"), (
        f"{name} sysext installs as {target!r} but downloads {source!r}; a still "
        "compressed image cannot be mounted by systemd-sysext"
    )


@pytest.mark.parametrize("name", sorted(COMPONENTS))
def test_component_sysext_image_name_matches_its_extension_release_name(name: str):
    """systemd-sysext requires ``extension-release.<image-name>`` to agree.

    The image a component transfer installs is merged through its stable
    ``CurrentSymlink`` name, so ``NAME=`` in its ``extension-release`` must be
    that name or the merge is rejected at boot.
    """
    release = COMPONENTS[name]["release"]
    assert release.is_file(), f"{release} missing"
    fields = dict(
        line.split("=", 1)
        for line in release.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    symlink = load_transfer(COMPONENTS[name]["transfer"])["Target"]["CurrentSymlink"]
    image_name = symlink.removesuffix(".raw")
    assert release.name == f"extension-release.{image_name}", (
        f"{release.name} does not match the installed image name {image_name!r}"
    )
    assert fields.get("NAME") == image_name, (
        f"extension-release NAME={fields.get('NAME')!r} but the sysext is merged "
        f"as {image_name!r}; systemd-sysext refuses the mismatch"
    )
    assert fields.get("ID") == "_any", (
        "ID must be _any: the sysext ships independently of the host os-release "
        "version and would otherwise be rejected after an OS update"
    )


@pytest.mark.parametrize("name", sorted(COMPONENTS))
def test_component_transfer_carries_no_feature_or_version_protection(name: str):
    """Components are opted into by enabling their activation unit, not by a
    feature, and are not tied to the booted image version."""
    transfer = load_transfer(COMPONENTS[name]["transfer"])["Transfer"]
    assert "Features" not in transfer and "ProtectVersion" not in transfer


IMAGE_ELEMENT = ELEMENTS_DIR / "oci" / "bluefin-server-image.bst"


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_every_source_artifact_is_in_the_signed_image_set(path: Path):
    """The asset a transfer downloads must be in the image set, whose signed
    SHA256SUMS the release publishes as-is (dist/diskless/)."""
    prefix, _ = split_match_pattern(load_transfer(path)["Source"]["MatchPattern"])
    image = IMAGE_ELEMENT.read_text()
    assert prefix in image, f"{path.name}: {prefix!r} assets are not in {IMAGE_ELEMENT.name}"
    build_yml = (REPO_ROOT / ".github" / "workflows" / "build.yml").read_text()
    assert "scripts/publish-release.sh release dist/diskless" in build_yml
    publish = (REPO_ROOT / "scripts" / "publish-release.sh").read_text()
    assert "-maxdepth 1 -type f" in publish
    assert "gpg --batch --yes --pinentry-mode loopback" in image
    assert "gpgv --keyring /boot-keys/import-pubring.pgp SHA256SUMS.gpg SHA256SUMS" in image


def test_k0s_release_staging_does_not_use_legacy_k3s_name() -> None:
    image = IMAGE_ELEMENT.read_text()
    assert "/sysext/k0s/k0s-*.raw.zst" in image
    assert "k3s-" not in image


def test_component_sysexts_are_staged_into_the_signed_image_set() -> None:
    image = IMAGE_ELEMENT.read_text()
    publish = (REPO_ROOT / "scripts" / "publish-release.sh").read_text()
    for name in COMPONENTS:
        assert f"filename: oci/{name}-sysext.bst" in image
        assert f"/sysext/{name}/{name}-*.raw.zst" in image
        # Own version axis: publish-release.sh accepts any version of it.
        assert f'"{name}-[0-9][0-9A-Za-z.+-]*\\\\.raw\\\\.zst"' in publish