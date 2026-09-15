"""Contract tests for dm-verity /usr image payload pinned by verity.usrhash.

Covers projectbluefin/server#135 (Phase 4 of the Flatcar base migration):
- DDI element emits an XFS /usr image with an appended verity hash tree at
  offset 1,065,345,024 and prints the root hash.
- Build enforces a hard size budget of 1,065,345,024 bytes and fails loudly when exceeded.
- Target UKI cmdline carries verity.usr=PARTLABEL=USR-A and verity.usrhash=<roothash>.
"""

from __future__ import annotations

import re
from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
DDI_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-ddi.bst"
INSTALLER_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-installer.bst"

VERITY_HASH_OFFSET = 1065345024
VERITY_BLOCK_SIZE = 4096
EXPECTED_DATA_BLOCKS = 260094


def _load_ddi_data() -> dict:
    content = DDI_ELEMENT.read_text(encoding="utf-8")
    return yaml.safe_load(content)


def test_verity_budget_and_blocks_alignment() -> None:
    """Verify that the verity offset aligns with standard 4096-byte sectors."""
    assert VERITY_HASH_OFFSET % VERITY_BLOCK_SIZE == 0
    assert VERITY_HASH_OFFSET // VERITY_BLOCK_SIZE == EXPECTED_DATA_BLOCKS


def test_ddi_depends_on_cryptsetup() -> None:
    """Verify bluefin-server-ddi.bst includes cryptsetup for veritysetup."""
    data = _load_ddi_data()
    build_depends = data.get("build-depends", [])
    dep_names = []
    for dep in build_depends:
        if isinstance(dep, str):
            dep_names.append(dep)
        elif isinstance(dep, dict) and "filename" in dep:
            dep_names.append(dep["filename"])

    assert "freedesktop-sdk.bst:components/cryptsetup.bst" in dep_names, (
        "bluefin-server-ddi.bst must include cryptsetup.bst in build-depends "
        "to format the dm-verity hash tree"
    )


def test_ddi_enforces_hard_size_budget() -> None:
    """Verify that the DDI checks payload size against the 1,065,345,024 budget and fails loudly."""
    content = DDI_ELEMENT.read_text(encoding="utf-8")

    assert "HASH_OFFSET=1065345024" in content
    assert re.search(r'\[\s*"\$\{ROOT_BYTES\}"\s+-ge\s*"\$\{HASH_OFFSET\}"\s*\]', content), (
        "DDI element must compare ROOT_BYTES against HASH_OFFSET"
    )
    assert 'truncate -s "${HASH_OFFSET}"' in content or "truncate -s 1065345024" in content, (
        "DDI image must be pre-allocated to the exact hash-offset budget"
    )


def test_ddi_appends_verity_hash_tree() -> None:
    """Verify veritysetup format is invoked with exact upstream parameters."""
    content = DDI_ELEMENT.read_text(encoding="utf-8")

    assert "veritysetup format" in content
    assert "--hash=sha256" in content
    assert "--data-block-size=4096" in content
    assert "--hash-block-size=4096" in content
    assert (
        '--data-blocks="${DATA_BLOCKS}"' in content
        or f"--data-blocks={EXPECTED_DATA_BLOCKS}" in content
    )
    assert (
        '--hash-offset="${HASH_OFFSET}"' in content
        or f"--hash-offset={VERITY_HASH_OFFSET}" in content
    )
    assert "--root-hash-file=" in content


def test_ddi_prints_and_exports_root_hash() -> None:
    """Verify that the DDI prints the root hash and saves verity.usrhash for UKI assembly."""
    content = DDI_ELEMENT.read_text(encoding="utf-8")

    assert 'echo "Verity root hash: ' in content
    assert "verity.usrhash" in content


def test_installer_reads_verity_usrhash_and_configures_uki() -> None:
    """Verify that the installer reads the verity root hash and pins it in UKI cmdline."""
    content = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert "/ddi/verity.usrhash" in content
    assert "verity.usr=PARTLABEL=USR-A" in content
    assert "verity.usrhash=" in content

    # UKI command line assertion
    uki_match = re.search(
        r'ukify build\s+.*?--cmdline="([^"]+)"\s+'
        r"[ \t\\\r\n]+--output=/target-root/boot/EFI/Linux/bluefin-server\.efi",
        content,
        flags=re.DOTALL,
    )
    assert uki_match, "ukify build command for target UKI must be present"
    cmdline = uki_match.group(1)
    assert "verity.usr=PARTLABEL=USR-A" in cmdline
    assert "verity.usrhash=${USR_HASH}" in cmdline
