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
FLATCAR_ZFS_ELEMENT = REPO_ROOT / "elements" / "flatcar" / "flatcar-zfs.bst"


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
    assert "test-installer-artifact:" in justfile
    assert "-device qemu-xhci,id=xhci" in justfile
    assert "-device usb-storage,bus=xhci.0,drive=installer-disk,bootindex=1" in justfile
    assert "-device virtio-blk-pci,drive=target-disk,bootindex=2" in justfile
    assert 'sfdisk --json "$WORKDIR/target.raw"' in justfile
    assert "bluefin-server-root-a" in justfile
    # The PXE pair is still exported, so the direct-kernel boot path stays covered.
    assert (
        '-append "systemd.unit=system-install.target '
        'console=tty0 console=ttyS0,115200 rw unattended"'
    ) in justfile


def test_installer_wrapper_reads_kernel_command_line_without_cat() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert 'CMDLINE="$(< /proc/cmdline)"' in installer_element
    assert 'CMDLINE="$(cat /proc/cmdline' not in installer_element


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


def test_ddi_generates_module_indexes_for_runtime_filesystem_drivers() -> None:
    ddi_element = DDI_ELEMENT.read_text(encoding="utf-8")

    assert "freedesktop-sdk.bst:components/kmod.bst" in ddi_element
    assert 'depmod -b /layer/usr "${KVER}"' in ddi_element
    assert "tls-ca-bundle.pem" in ddi_element
    assert "ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service" in ddi_element
    assert "ln -sf /dev/null /layer/etc/systemd/system/systemd-homed-firstboot.service" in ddi_element
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
    assert 'udevadm settle --timeout="${SETTLE_TIMEOUT}" || true' in installer_element
    assert "After=systemd-udev-settle.service" in installer_element
    assert "Wants=systemd-udev-settle.service" in installer_element


def test_installer_hard_preflight_aborts_on_missing_installer_data_part() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert 'DEADLINE=$((SECONDS + 30))' in installer_element
    assert 'while [ ! -b "${INSTALLER_PART_PATH}" ] && [ "${SECONDS}" -lt "${DEADLINE}" ]; do' in installer_element
    assert '[ ! -b "${INSTALLER_PART_PATH}" ]' in installer_element
    assert "/dev/disk/by-partlabel/bluefin-installer-data" in installer_element
    assert "lsblk -p -o NAME,TYPE,PARTLABEL,PKNAME,SIZE,FSTYPE" in installer_element


def test_interactive_installer_uses_local_virtual_console() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")

    assert "TTYPath=/dev/tty0" in installer_element
    assert "StandardOutput=journal+console" in installer_element
    assert "StandardError=journal+console" in installer_element
    # journal+console follows the last console= argument (ttyS0), so the wrapper has
    # to put interactive runs back on the attached display itself — but only when the
    # kernel actually registered tty0 as a console, otherwise serial-only machines
    # lose the install output to a VT nobody is watching.
    assert (
        'if [[ " ${CMDLINE} " != *" unattended "* ]] \\\n'
        "         && [ -w /dev/tty0 ] \\\n"
        "         && grep -qw tty0 /sys/class/tty/console/active 2>/dev/null; then\n"
        "        exec > /dev/tty0 2>&1"
    ) in installer_element


def test_installer_and_ddi_strip_vmlinux_and_static_archives() -> None:
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    ddi_element = DDI_ELEMENT.read_text(encoding="utf-8")

    assert 'rm -f "/layer/usr/lib/modules/${KVER}/vmlinux"' in installer_element
    assert "find /layer -type f -name '*.a' -delete" in installer_element
    assert 'rm -f "/layer/usr/lib/modules/${KVER}/vmlinux"' in ddi_element
    assert "find /layer -type f -name '*.a' -delete" in ddi_element


def test_flatcar_zfs_removes_udevd_sysext_ordering_dropin() -> None:
    flatcar_zfs = FLATCAR_ZFS_ELEMENT.read_text(encoding="utf-8")

    assert (
        'rm -rf "%{install-root}/usr/lib/systemd/system/systemd-udevd.service.d"'
        in flatcar_zfs
    )
    assert (
        'sed -i "/systemd-udevd\\.service\\.d/d" "%{install-root}/usr/lib/tmpfiles.d/10-zfs.conf"'
        in flatcar_zfs
    )
    assert "freedesktop-sdk.bst:components/sed.bst" in flatcar_zfs

    # The preserved raw sysext must be rebuilt from the cleaned tree, not the
    # untouched upstream image, so the ordering override cannot come back if the
    # raw is ever merged at runtime.
    assert "install -D -m 0644 flatcar-zfs.raw" not in flatcar_zfs
    assert (
        'mksquashfs "%{install-root}" zfs-cleaned.raw -noappend -no-xattrs -all-root'
        in flatcar_zfs
    )
    assert flatcar_zfs.index("mksquashfs") > flatcar_zfs.index(
        'rm -rf "%{install-root}/usr/lib/systemd/system/systemd-udevd.service.d"'
    )


def test_var_partition_contracts_use_consistent_partlabel() -> None:
    import base64

    repart_var = (
        REPO_ROOT / "files" / "installer" / "repart.d" / "30-var.conf"
    ).read_text(encoding="utf-8")
    ddi_element = DDI_ELEMENT.read_text(encoding="utf-8")
    var_mount = (
        REPO_ROOT / "files" / "os" / "systemd" / "system" / "var.mount"
    ).read_text(encoding="utf-8")
    justfile = JUSTFILE.read_text(encoding="utf-8")

    assert "Label=var" in repart_var
    assert "/dev/disk/by-partlabel/var /var xfs defaults 0 0" in ddi_element
    assert "What=/dev/disk/by-partlabel/var" in var_mount
    expected_b64 = base64.b64encode(
        b"/dev/disk/by-partlabel/var /var xfs defaults 0 0\n"
    ).decode("ascii")
    assert expected_b64 in justfile


def test_installer_smoke_probes_the_kiosk_over_tls_from_inside_the_guest() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert "systemd.mask=systemd-homed-firstboot.service" in justfile
    assert "https://127.0.0.1:8080/healthz" in justfile
    assert "--insecure" in justfile
    assert "systemd.extra-unit.bluefin-kiosk-ready.service" in justfile
    assert "systemd.wants=bluefin-kiosk-ready.service" in justfile
    # The host cannot reach the guest's loopback-bound kiosk proxy, so no
    # host-side probe may remain in the smoke test — a stray host process on
    # port 8080 would otherwise let it pass without the guest being ready.
    smoke = justfile.split("install-vm:")[0]
    assert "http://127.0.0.1:8080/healthz" not in smoke
    assert "KIOSK_CONSOLE_READY" in smoke


def test_test_installer_boot_usb_contract() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("test-installer-boot-usb:")
    end = justfile.index("test-installer-boot-pxe:", start)
    recipe = justfile[start:end]
    assert "INSTALLER_BOOT_MODE=usb just test-installer-artifact" in recipe


def test_test_installer_boot_pxe_recipe_exercises_direct_kernel_boot() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("test-installer-boot-pxe:")
    end = justfile.index("install-vm:", start)
    recipe = justfile[start:end]
    assert "INSTALLER_BOOT_MODE=pxe just test-installer-artifact" in recipe
    assert '-kernel "$WORKDIR/installer.vmlinuz"' in justfile
    assert '-initrd "$WORKDIR/installer.initrd"' in justfile
    assert "bluefin-server-pxe-vmlinuz-*" in justfile
    assert "bluefin-server-pxe-initrd-*.cpio.gz" in justfile
