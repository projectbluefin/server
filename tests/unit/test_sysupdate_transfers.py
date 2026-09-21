"""Unit coverage for the OS and component sysupdate transfer definitions.

``tests/unit/test_repart_layout.py`` already pins ``50-root.transfer`` against
the installer repart config. The other two OTA transfer definitions —
``60-uki.transfer`` (the boot UKI) and ``70-kubernetes.transfer`` (the
Kubernetes sysext) — have no coverage at all, and neither does the source-side
artifact naming that systemd-sysupdate matches against.

These tests assert the drift-prone contracts:

* every transfer parses and carries ``[Transfer]``/``[Source]``/``[Target]``
* every source pulls from this repo's own release feed over https
* every source ``MatchPattern`` corresponds to an artifact name that some
  element under ``elements/`` actually emits (``bluefin-server-ddi-<v>.raw.zst``,
  ``bluefin-server-<v>.efi``, ``kubernetes-<v>.raw.zst``)
* the Kubernetes sysext transfer lands in ``/var/lib/extensions`` under a name
  that ``files/kubernetes/sysext/extension-release.kubernetes``
  (``NAME=kubernetes``) can merge
"""

import configparser
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SYSUPDATE_DIR = REPO_ROOT / "files" / "os" / "sysupdate.d"
KUBERNETES_SYSUPDATE_DIR = REPO_ROOT / "files" / "os" / "sysupdate.kubernetes.d"
KUBERNETES_TRANSFER = KUBERNETES_SYSUPDATE_DIR / "70-kubernetes.transfer"
ELEMENTS_DIR = REPO_ROOT / "elements"
EXTENSION_RELEASE = (
    REPO_ROOT / "files" / "kubernetes" / "sysext" / "extension-release.kubernetes"
)

RELEASE_FEED = "https://github.com/projectbluefin/server/releases/latest/download/"


def transfer_paths() -> list[Path]:
    return sorted(
        (
            *SYSUPDATE_DIR.glob("*.transfer"),
            *KUBERNETES_SYSUPDATE_DIR.glob("*.transfer"),
        )
    )


def load_transfer(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False)
    # systemd keys are case sensitive; configparser lowercases them by default.
    parser.optionxform = str
    parser.read_string(path.read_text())
    return parser


def element_texts() -> str:
    """Every element definition concatenated, for artifact-name lookups."""
    return "\n".join(
        p.read_text() for p in sorted(ELEMENTS_DIR.rglob("*.bst"))
    )


def split_match_pattern(pattern: str) -> tuple[str, str]:
    """Return the literal ``(prefix, suffix)`` around sysupdate's ``@v`` token."""
    assert "@v" in pattern, f"MatchPattern {pattern!r} carries no @v version token"
    prefix, _, suffix = pattern.partition("@v")
    return prefix, suffix


def test_sysupdate_directories_are_populated():
    generic = sorted(p.name for p in SYSUPDATE_DIR.glob("*.transfer"))
    kubernetes = sorted(
        p.name for p in KUBERNETES_SYSUPDATE_DIR.glob("*.transfer")
    )
    assert generic == ["50-root.transfer", "60-uki.transfer"]
    assert kubernetes == ["70-kubernetes.transfer"]


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
    system as up to date forever.
    """
    prefix, suffix = split_match_pattern(
        load_transfer(path)["Source"]["MatchPattern"]
    )
    # Elements name artifacts with a BuildStream variable in the version slot,
    # e.g. FNAME="kubernetes-%{k8s-version}.raw" plus a .zst compression step.
    produced = re.compile(
        re.escape(prefix) + r"%\{[a-z0-9-]+\}" + re.escape(suffix.removesuffix(".zst"))
    )
    assert produced.search(element_texts()), (
        f"{path.name} expects release asset {prefix}<version>{suffix}, but no "
        f"element under {ELEMENTS_DIR} emits a file named that way"
    )


def test_uki_transfer_installs_into_the_esp_boot_directory():
    target = load_transfer(SYSUPDATE_DIR / "60-uki.transfer")["Target"]
    assert target.get("Type") == "regular-file", (
        "the UKI is a regular-file drop-in, not a partition or directory"
    )
    assert target.get("Path") == "/efi/EFI/Linux", (
        f"UKI target path is {target.get('Path')!r}; systemd-boot only discovers "
        "unified kernels under the ESP's EFI/Linux directory"
    )
    assert target.get("MatchPattern", "").endswith(".efi"), (
        "the installed UKI must keep its .efi extension to be bootable"
    )


def test_uki_source_and_target_names_agree():
    parser = load_transfer(SYSUPDATE_DIR / "60-uki.transfer")
    assert parser["Source"]["MatchPattern"] == parser["Target"]["MatchPattern"], (
        "the UKI is copied verbatim; a source/target name mismatch would leave "
        "sysupdate unable to correlate installed and available versions"
    )


def test_kubernetes_sysext_transfer_lands_where_systemd_sysext_scans() -> None:
    """The image must be merged by systemd-sysext.service, not by a copy step.

    ``/var/lib/extensions`` is one of systemd-sysext's own search paths, so an
    image landing there is merged at boot with no unit shuffling it into
    ``/run/extensions`` first.
    """
    target = load_transfer(KUBERNETES_TRANSFER)["Target"]
    assert target.get("Type") == "regular-file", (
        "the Kubernetes sysext is delivered as a decompressed regular file"
    )
    assert target.get("Path") == "/var/lib/extensions", (
        f"sysext target path is {target.get('Path')!r}; anywhere else and "
        "systemd-sysext.service never sees the image"
    )
    assert target.get("Mode") == "0644", (
        f"sysext mode is {target.get('Mode')!r}; the image must be readable "
        "by systemd-sysext at merge time"
    )


def test_kubernetes_sysext_transfer_maintains_a_stable_current_symlink():
    target = load_transfer(KUBERNETES_TRANSFER)["Target"]
    symlink = target.get("CurrentSymlink")
    assert symlink == "kubernetes.raw", (
        f"CurrentSymlink is {symlink!r}; the merge name must be stable, so a "
        "version bump otherwise stops merging the sysext"
    )
    prefix, suffix = split_match_pattern(target["MatchPattern"])
    assert symlink == f"{prefix.rstrip('-')}{suffix}", (
        f"CurrentSymlink {symlink!r} does not follow the versioned target name "
        f"{target['MatchPattern']!r}"
    )


def test_kubernetes_sysext_transfer_decompresses_the_release_asset():
    parser = load_transfer(KUBERNETES_TRANSFER)
    source = parser["Source"]["MatchPattern"]
    target = parser["Target"]["MatchPattern"]
    assert source == "kubernetes-@v.raw.zst", (
        f"release asset pattern is {source!r}; "
        ".github/scripts/check-kubernetes-version.py cross-checks this exact "
        "spelling against the name elements/oci/kubernetes-sysext.bst emits"
    )
    assert target == source.removesuffix(".zst"), (
        f"sysext installs as {target!r} but downloads {source!r}; a still "
        "compressed image cannot be mounted by systemd-sysext"
    )


def test_kubernetes_sysext_image_name_matches_its_extension_release_name():
    """systemd-sysext requires ``extension-release.<image-name>`` to agree.

    The image installed by ``70-kubernetes.transfer`` is merged through the
    stable ``kubernetes.raw`` symlink, so ``NAME=`` in
    ``files/kubernetes/sysext/extension-release.kubernetes`` must be
    ``kubernetes`` or the merge is rejected at boot.
    """
    assert EXTENSION_RELEASE.is_file(), f"{EXTENSION_RELEASE} missing"
    fields = dict(
        line.split("=", 1)
        for line in EXTENSION_RELEASE.read_text().splitlines()
        if "=" in line and not line.startswith("#")
    )
    symlink = load_transfer(KUBERNETES_TRANSFER)["Target"]["CurrentSymlink"]
    image_name = symlink.removesuffix(".raw")
    assert EXTENSION_RELEASE.name == f"extension-release.{image_name}", (
        f"{EXTENSION_RELEASE.name} does not match the installed image name "
        f"{image_name!r}"
    )
    assert fields.get("NAME") == image_name, (
        f"extension-release NAME={fields.get('NAME')!r} but the sysext is merged "
        f"as {image_name!r}; systemd-sysext refuses the mismatch"
    )
    assert fields.get("ID") == "_any", (
        "ID must be _any: the sysext ships independently of the host os-release "
        "version and would otherwise be rejected after an OS update"
    )


@pytest.mark.parametrize("path", transfer_paths(), ids=lambda p: p.name)
def test_every_source_artifact_is_staged_in_release_workflow(path: Path):
    """The release asset a transfer downloads must be staged into dist/release/ by build.yml."""
    prefix, _ = split_match_pattern(
        load_transfer(path)["Source"]["MatchPattern"]
    )
    build_yml = (REPO_ROOT / ".github" / "workflows" / "build.yml").read_text()
    assert re.search(rf"cp\s+.*{re.escape(prefix)}\*.*dist/release/", build_yml), (
        f"{path.name} source asset prefix {prefix!r} is not staged to dist/release/ in .github/workflows/build.yml"
    )
