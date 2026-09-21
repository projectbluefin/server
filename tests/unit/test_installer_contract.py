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
DDI_ELEMENT = REPO_ROOT / "elements" / "oci" / "bluefin-server-ddi.bst"


def _published_uki_cmdline(installer_element: str) -> str:
    match = re.search(
        r'ukify build\s+.*?--cmdline="([^"]+)"\s+'
        r"[ \t\\\r\n]+--output=/layer/boot/efi/EFI/BOOT/BOOTX64\.EFI",
        installer_element,
        flags=re.DOTALL,
    )
    assert match, "published Installer UKI ukify command must be present"
    return match.group(1)


def _target_uki_cmdline(installer_element: str) -> str:
    match = re.search(
        r'ukify build\s+.*?--cmdline="([^"]+)"\s+'
        r"[ \t\\\r\n]+--output=/target-root/boot/EFI/Linux/bluefin-server\.efi",
        installer_element,
        flags=re.DOTALL,
    )
    assert match, "target UKI ukify command must be present"
    return match.group(1)


def test_installer_runtime_and_boot_contracts() -> None:
    installer_stack = INSTALLER_STACK.read_text(encoding="utf-8")
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    justfile = JUSTFILE.read_text(encoding="utf-8")
    published_uki_cmdline = _published_uki_cmdline(installer_element)
    target_uki_cmdline = _target_uki_cmdline(installer_element)

    assert "freedesktop-sdk.bst:bootstrap/bash.bst" in installer_stack
    assert "console=ttyS0,115200 rw" in installer_element
    assert "unattended" not in published_uki_cmdline
    assert target_uki_cmdline == "rw console=ttyS0,115200 console=tty0 quiet loglevel=3 audit=0"
    assert (
        '-append "systemd.unit=system-install.target '
        'console=tty0 console=ttyS0,115200 rw unattended"'
    ) in justfile


def test_installer_wrapper_reads_kernel_command_line_without_cat() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert 'CMDLINE="$(< /proc/cmdline)"' in installer_element
    assert 'CMDLINE="$(cat /proc/cmdline' not in installer_element


def test_installer_stages_uncompressed_sysext_before_packing_cpio() -> None:
    """The sysext has to be in /layer before the initrd is packed, or the
    offline installer ships no Kubernetes at all."""
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    data = yaml.safe_load(installer_element)
    sysext_dependency = next(
        (
            dependency
            for dependency in data["build-depends"]
            if isinstance(dependency, dict)
            and dependency.get("filename") == "oci/kubernetes-sysext.bst"
        ),
        None,
    )

    assert sysext_dependency == {
        "filename": "oci/kubernetes-sysext.bst",
        "config": {"location": "/kubernetes"},
    }

    seed_command = "cp /kubernetes/kubernetes-*.raw /layer/kubernetes.raw"
    cpio_command = "| cpio --null --create --format=newc"
    assert seed_command in installer_element
    assert installer_element.index(seed_command) < installer_element.index(
        cpio_command
    )


def test_ddi_generates_module_indexes_for_runtime_filesystem_drivers() -> None:
    ddi_element = DDI_ELEMENT.read_text(encoding="utf-8")

    assert "freedesktop-sdk.bst:components/kmod.bst" in ddi_element
    assert 'depmod -b /layer/usr "${KVER}"' in ddi_element
    assert "cp -a /etc/pki/ca-trust/extracted/* /layer/etc/pki/ca-trust/extracted/" in ddi_element
    assert "tls-ca-bundle.pem" in ddi_element
    assert "ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service" in ddi_element
    assert "ln -sf /dev/null /layer/etc/systemd/system/systemd-homed-firstboot.service" in ddi_element
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert "systemd.mask=systemd-homed-firstboot.service" in justfile
    assert "hostfwd=tcp:127.0.0.1:2222-:22" in justfile
    assert "systemd.wants=sshd.service" in justfile
    assert "ssh.authorized_keys.root=" in justfile
    assert "find dist/ -maxdepth 1 -type f -name 'bluefin-server-installer-*.raw.zst'" in justfile
    assert 'if [ "$ROOT_CODE" = "200" ]; then' in justfile
    assert '[ "$ROOT_CODE" = "503" ]' not in justfile
    assert "ln -sf /dev/null /layer/etc/systemd/system/audit-rules.service" in ddi_element
    assert "printf '127.0.0.1   localhost" in ddi_element
    assert "> /layer/etc/hosts" in ddi_element


def test_target_initramfs_preloads_sysext_filesystem_drivers() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert (
        '--add-drivers "virtio virtio_blk virtio_pci virtio_scsi nvme nvme_core xfs erofs overlay zfs spl"'
        in installer_element
    )


def test_installer_loads_storage_drivers_and_settles_udev() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert "modprobe -q nvme || true" in installer_element
    assert "modprobe -q nvme_core || true" in installer_element
    assert "modprobe -q usb-storage || true" in installer_element
    assert "modprobe -q uas || true" in installer_element
    assert "udevadm settle --timeout=15 || true" in installer_element
    assert "After=systemd-udev-settle.service" in installer_element
    assert "Wants=systemd-udev-settle.service" in installer_element

def test_interactive_installer_uses_local_virtual_console() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert "TTYPath=/dev/tty0" in installer_element


def test_installer_and_ddi_strip_vmlinux_and_static_archives() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    ddi_element = DDI_ELEMENT.read_text(encoding="utf-8")

    assert 'rm -f "/layer/usr/lib/modules/${KVER}/vmlinux"' in installer_element
    assert "find /layer -type f -name '*.a' -delete" in installer_element
    assert 'rm -f "/layer/usr/lib/modules/${KVER}/vmlinux"' in ddi_element
    assert "find /layer -type f -name '*.a' -delete" in ddi_element
