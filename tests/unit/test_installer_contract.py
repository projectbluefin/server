"""Contracts for the published Installer and headless smoke boot."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER_STACK = REPO_ROOT / "elements" / "installer" / "installer-stack.bst"
INSTALLER_ELEMENT = (
    REPO_ROOT / "elements" / "oci" / "bluefin-server-installer.bst"
)
JUSTFILE = REPO_ROOT / "Justfile"


def _published_uki_cmdline(installer_element: str) -> str:
    match = re.search(
        r'ukify build\s+.*?--cmdline="([^"]+)"\s+'
        r"[ \t\\\r\n]+--output=/layer/boot/efi/EFI/BOOT/BOOTX64\.EFI",
        installer_element,
        flags=re.DOTALL,
    )
    assert match, "published Installer UKI ukify command must be present"
    return match.group(1)


def test_installer_runtime_and_boot_contracts() -> None:
    installer_stack = INSTALLER_STACK.read_text(encoding="utf-8")
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    justfile = JUSTFILE.read_text(encoding="utf-8")
    published_uki_cmdline = _published_uki_cmdline(installer_element)

    assert "freedesktop-sdk.bst:bootstrap/bash.bst" in installer_stack
    assert 'console=ttyS0,115200 rw"' in installer_element
    assert "unattended" not in published_uki_cmdline
    assert (
        '-append "systemd.unit=system-install.target '
        'console=tty0 console=ttyS0,115200 rw unattended"'
    ) in justfile


def test_installer_stages_uncompressed_k0s_before_packing_cpio() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    data = yaml.safe_load(installer_element)
    k0s_dependency = next(
        (
            dependency
            for dependency in data["build-depends"]
            if isinstance(dependency, dict)
            and dependency.get("filename") == "oci/k0s-sysext.bst"
        ),
        None,
    )

    assert k0s_dependency == {
        "filename": "oci/k0s-sysext.bst",
        "config": {"location": "/k0s"},
    }

    seed_command = "cp /k0s/k0s-*.raw /layer/k0s.raw"
    cpio_command = "| cpio --null --create --format=newc"
    assert seed_command in installer_element
    assert installer_element.index(seed_command) < installer_element.index(
        cpio_command
    )
