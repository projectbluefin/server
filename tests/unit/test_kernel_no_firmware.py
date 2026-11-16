"""Contracts for patch 0009: no firmware-bound drivers, zstd vmlinuz.

The image ships no /usr/lib/firmware, so 0009 turns off Wi-Fi, Bluetooth and
the amdgpu/radeon/nouveau/xe GPU drivers in FSDK's fdsdk-config.sh and takes
exactly the options that turned off out of FSDK's expected-configs check.
"""


import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATCH = ROOT / "patches" / "freedesktop-sdk" / "0009-linux-server-no-firmware-hw.patch"


def _added_lines() -> list[str]:
    return [
        line[1:]
        for line in PATCH.read_text().splitlines()
        if line.startswith("+") and not line.startswith("+++")
    ]


def _added_code() -> list[str]:
    return [line.strip() for line in _added_lines() if line.strip() and not line.lstrip().startswith("#")]


@pytest.mark.parametrize(
    "option",
    ["WLAN", "CFG80211", "MAC80211", "BT", "DRM_AMDGPU", "DRM_RADEON", "DRM_NOUVEAU", "DRM_XE", "KERNEL_GZIP"],
)
def test_option_is_removed(option: str) -> None:
    assert f"remove {option}" in _added_code()


def test_vmlinuz_is_zstd() -> None:
    assert "enable KERNEL_ZSTD" in _added_code()


def test_zstd_vmlinuz_is_arch_guarded() -> None:
    """arm64 selects no HAVE_KERNEL_*, so KERNEL_ZSTD stays unset there and
    FSDK's `enable` would fail linux.bst with "Missing KERNEL_ZSTD": the
    compression switch must sit inside an x86_64-only case."""
    code = _added_code()
    case = code.index('case "$arch" in')
    esac = code.index("esac", case)
    guarded = code[case:esac]
    assert guarded[1] == "x86_64)"
    assert "remove KERNEL_GZIP" in guarded and "enable KERNEL_ZSTD" in guarded
    assert code.count("enable KERNEL_ZSTD") == 1 and code.count("remove KERNEL_GZIP") == 1


@pytest.mark.parametrize(
    "option",
    [
        "DEBUG_INFO_BTF",  # Cilium CO-RE
        "SOUND", "SND", "MEDIA_SUPPORT", "IIO", "INPUT_JOYSTICK",  # a product call, not this patch
        "DRM_I915", "DRM_SIMPLEDRM", "DRM_VIRTIO_GPU", "DRM_HYPERV", "DRM_VMWGFX", "DRM_AST", "DRM_MGAG200",
        "DRM_BOCHS", "RFKILL",
    ],
)
def test_option_is_not_touched(option: str) -> None:
    for line in _added_code():
        assert option not in line.split(), line


def test_patch_targets_fsdk_linux_config_script() -> None:
    text = PATCH.read_text()
    assert "diff --git a/files/linux/fdsdk-config.sh b/files/linux/fdsdk-config.sh" in text


def test_expected_configs_lose_only_what_the_block_turned_off(tmp_path: Path) -> None:
    """Run the block against stub config helpers: a dependent of a removed
    option leaves expected-configs, an unrelated option stays, and an option
    FSDK expects but Kconfig never set stays (so the build still fails)."""
    (tmp_path / "block.sh").write_text("\n".join(_added_lines()) + "\n")
    (tmp_path / "state").write_text("CFG80211=y\nIWLWIFI=m\nVXLAN=m\nKERNEL_GZIP=y\n")
    (tmp_path / "expected-configs").write_text("CFG80211\nIWLWIFI\nVXLAN\nRENAMED_UPSTREAM\n")
    stubs = r"""
set -eu
has() { grep -Eqx "$1=[ym]" state; }
remove() { sed -i "/^$1=/d" state; }
enable() { echo "$1" >>expected-configs; echo "$1=y" >>state; }
make() { has CFG80211 || sed -i '/^IWLWIFI=/d' state; }
. ./block.sh
"""
    subprocess.run(["bash", "-c", "arch=x86_64\n" + stubs], cwd=tmp_path, check=True, capture_output=True)
    assert (tmp_path / "expected-configs").read_text().split() == ["VXLAN", "RENAMED_UPSTREAM", "KERNEL_ZSTD"]
    assert (tmp_path / "no-firmware-configs").read_text().split() == ["CFG80211", "IWLWIFI"]


def test_aarch64_does_not_expect_kernel_zstd(tmp_path: Path) -> None:
    """On aarch64 the block must neither enable KERNEL_ZSTD nor add it to
    expected-configs (Kconfig offers no compression choice on arm64)."""
    (tmp_path / "block.sh").write_text("\n".join(_added_lines()) + "\n")
    (tmp_path / "state").write_text("VXLAN=m\n")
    (tmp_path / "expected-configs").write_text("VXLAN\n")
    stubs = r"""
set -eu
arch=aarch64
has() { grep -Eqx "$1=[ym]" state; }
remove() { sed -i "/^$1=/d" state; }
enable() { echo "$1" >>expected-configs; echo "$1=y" >>state; }
make() { :; }
. ./block.sh
"""
    subprocess.run(["bash", "-c", stubs], cwd=tmp_path, check=True, capture_output=True)
    assert (tmp_path / "expected-configs").read_text().split() == ["VXLAN"]


def test_patches_readme_documents_the_patch() -> None:
    assert PATCH.name in (ROOT / "patches" / "README.md").read_text()
