"""Contracts for the published Installer and headless smoke boot."""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest
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


def test_installer_wrapper_does_not_call_sed_awk_or_tar(installer_wrapper: str) -> None:
    # The released 26.08.0 PXE initrd failed with "sed: command not found"
    # (exit 127) right after a successful download: the live initrd ships
    # uutils coreutils, grep, curl, zstd and systemd, but no sed, awk or tar,
    # so no command position may name any of them. Only a '#' at the start of
    # a line or after whitespace opens a comment; '#' inside a string does not.
    code_lines = [re.sub(r"(^|\s)#.*$", "", line) for line in installer_wrapper.splitlines()]
    invoked = re.compile(r"(?:^|[\s|;&(`$])(sed|awk|tar)(?=[\s;|&)>]|$)")
    offenders = [line for line in code_lines if invoked.search(line)]
    assert offenders == [], offenders


def test_installer_build_pins_every_external_command_the_wrapper_calls() -> None:
    # Step 1a of the element refuses to pack an initrd that lacks any of the
    # wrapper's external commands, so a missing tool fails the build rather
    # than the install (exit 127 after the DDI download, as sed did).
    installer_element = INSTALLER_ELEMENT.read_text(encoding="utf-8")
    match = re.search(r"for tool in ((?:[^;\n]|\\\n)+); do", installer_element)
    assert match, "the build-time tool check loop must be present"
    pinned = set(match.group(1).replace("\\\n", " ").split())
    for tool in (
        "grep", "curl", "zstd", "modprobe", "mount", "umount", "sha256sum",
        "readlink", "lsblk", "udevadm", "systemd-sysinstall", "systemctl",
        "mountpoint", "stat", "df", "tail",
    ):
        assert tool in pinned, f"{tool} is called by bluefin-sysinstall but not pinned at build time"


def _copyblocks_repoint_block(installer_wrapper: str) -> tuple[str, str]:
    """The CopyBlocks= rewrite carved out of the wrapper, plus the repointed line.

    Coupled to the element text: the slice starts at the ROOT_COPYBLOCKS_LINE
    assignment (column 0 after the fixture de-indents the heredoc) and ends at
    the ``fi`` closing the ROOT_COPYBLOCKS_SEEN check.
    """
    start = installer_wrapper.index('ROOT_COPYBLOCKS_LINE="CopyBlocks=')
    seen_if = installer_wrapper.index('if [ "${ROOT_COPYBLOCKS_SEEN}" -eq 0 ]', start)
    end = re.compile(r"^[ \t]*fi\n", re.MULTILINE).search(installer_wrapper, seen_if).end()
    block = installer_wrapper[start:end]

    copyblocks = re.search(r'^ROOT_COPYBLOCKS_LINE="(CopyBlocks=/\S+)"$', block, flags=re.MULTILINE)
    assert copyblocks, "the wrapper must pin the repointed CopyBlocks= line in ROOT_COPYBLOCKS_LINE"
    return block, copyblocks.group(1)


def _run_copyblocks_repoint(
    tmp_path: Path, installer_wrapper: str, recipe_text: str
) -> tuple[subprocess.CompletedProcess[str], Path, str]:
    block, copyblocks_line = _copyblocks_repoint_block(installer_wrapper)
    src_dir = tmp_path / "repart.d"
    dst_dir = tmp_path / "repart.sysinstall.d"
    src_dir.mkdir(parents=True)
    dst_dir.mkdir(parents=True)
    (src_dir / "20-root-a.conf").write_text(recipe_text, encoding="utf-8")
    block = block.replace("/usr/lib/repart.d", shlex.quote(str(src_dir))).replace(
        "/usr/lib/repart.sysinstall.d", shlex.quote(str(dst_dir))
    )
    result = subprocess.run(
        ["bash", "-euo", "pipefail", "-c", block], capture_output=True, text=True
    )
    return result, dst_dir / "20-root-a.conf", copyblocks_line


def test_installer_wrapper_copyblocks_repoint_matches_the_sed_it_replaced(
    tmp_path: Path, installer_wrapper: str
) -> None:
    """Run the Bash rewrite against the shipped recipe: only the CopyBlocks= line changes."""
    recipe = (REPO_ROOT / "files" / "installer" / "repart.d" / "20-root-a.conf").read_text(
        encoding="utf-8"
    )
    result, output, copyblocks_line = _run_copyblocks_repoint(tmp_path, installer_wrapper, recipe)
    assert result.returncode == 0, result.stderr

    expected = re.sub(r"^CopyBlocks=.*$", copyblocks_line, recipe, flags=re.MULTILINE)
    assert output.read_text(encoding="utf-8") == expected
    assert f"{copyblocks_line}\n" in expected


def test_installer_wrapper_copyblocks_repoint_fails_closed_without_a_copyblocks_line(
    tmp_path: Path, installer_wrapper: str
) -> None:
    # Recipe and wrapper ship from the same repo; a recipe with no column-0
    # CopyBlocks= line is a repo bug, so the wrapper must error out before the
    # disk is touched rather than guess where to put the key. An indented key
    # (valid for systemd's parser) is deliberately not matched and hits the
    # same error, instead of silently producing a second CopyBlocks= line.
    for recipe in (
        "[Partition]\nType=root\nLabel=bluefin-server-root-a\n",
        "[Partition]\nType=root\n  CopyBlocks=/dev/disk/by-partlabel/x\n",
    ):
        result, output, copyblocks_line = _run_copyblocks_repoint(
            tmp_path / str(len(recipe)), installer_wrapper, recipe
        )
        assert result.returncode == 1, (result.returncode, result.stderr)
        assert "20-root-a.conf has no CopyBlocks= line" in result.stderr
        assert copyblocks_line not in output.read_text(encoding="utf-8")


def test_installer_network_ddi_stages_in_dev_shm_with_space_preflight(installer_wrapper: str) -> None:
    wrapper = installer_wrapper

    # /run is a tmpfs capped at 20% of RAM and cannot hold the decompressed DDI
    # on an 8 GiB machine; /dev/shm is at the kernel tmpfs default of 50%.
    assert "mountpoint -q /dev/shm ||" in wrapper
    assert "mkdir -p /dev/shm/installer" in wrapper
    assert "/run/installer" not in wrapper
    assert '--output /dev/shm/installer/bluefin-server-ddi.raw.zst "${DDI_URL}"' in wrapper
    assert "-o /dev/shm/installer/bluefin-server-ddi.raw ||" in wrapper
    assert "CopyBlocks=/dev/shm/installer/bluefin-server-ddi.raw" in wrapper

    # Free space is checked against the raw size (frame header, else 5x the
    # compressed size) after verification and before zstd runs, so a machine
    # with too little RAM gets a clear error instead of ENOSPC mid-write or an
    # OOM kill. Both the tmpfs cap (df) and MemAvailable bound the check. The
    # comparison is in KiB, rounded up, so a raw image a few KiB over the free
    # space is not waved through by MiB truncation.
    verify = wrapper.index("sha256sum --check --status")
    preflight = wrapper.index("ERROR: not enough RAM-backed temporary space in /dev/shm/installer")
    decompress = wrapper.index("zstd -d -q --rm")
    assert verify < preflight < decompress
    assert 'DDI_ZST_BYTES="$(stat -c %s /dev/shm/installer/bluefin-server-ddi.raw.zst)"' in wrapper
    assert "DDI_RAW_BYTES=$(( DDI_ZST_BYTES * 5 ))" in wrapper
    assert 'DDI_STAGE_AVAIL_KIB="$(df -k --output=avail /dev/shm/installer | tail -n1)"' in wrapper
    assert "DDI_MEMINFO=/proc/meminfo" in wrapper
    assert 'if [ "${key}" = "MemAvailable:" ]; then' in wrapper
    assert "DDI_NEED_KIB=$(( (DDI_RAW_BYTES + 1023) / 1024 ))" in wrapper
    assert 'if [ "${DDI_HAVE_KIB}" -lt "${DDI_NEED_KIB}" ]; then' in wrapper


def _space_preflight_block(wrapper: str) -> str:
    """The preflight carved out of the wrapper: from the stat of the download to the fi of the size check."""
    start = wrapper.index('DDI_ZST_BYTES="$(stat -c %s')
    size_if = wrapper.index('if [ "${DDI_HAVE_KIB}" -lt "${DDI_NEED_KIB}" ]', start)
    end = re.compile(r"^[ \t]*fi\n", re.MULTILINE).search(wrapper, size_if).end()
    return wrapper[start:end]


def _run_space_preflight(
    tmp_path: Path,
    block: str,
    payload: bytes,
    avail_kib: int,
    mem_available_kib: int = 64 * 1024 * 1024,
    meminfo_text: str | None = None,
) -> subprocess.CompletedProcess:
    """Run the preflight with a stand-in df (right-aligned like the real one) and a fake /proc/meminfo."""
    stage = tmp_path / "stage"
    stage.mkdir(parents=True)
    (stage / "bluefin-server-ddi.raw.zst").write_bytes(payload)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "df").write_text(
        f"#!/bin/bash\nprintf '   Avail\\n %d\\n' {avail_kib}\n", encoding="utf-8"
    )
    (fake_bin / "df").chmod(0o755)
    meminfo = tmp_path / "meminfo"
    if meminfo_text is None:
        meminfo_text = (
            "MemTotal:       16000000 kB\n"
            "MemFree:         1000000 kB\n"
            f"MemAvailable:   {mem_available_kib} kB\n"
            "Buffers:              10 kB\n"
        )
    meminfo.write_text(meminfo_text, encoding="utf-8")
    script = block.replace("/dev/shm/installer", shlex.quote(str(stage))).replace(
        "DDI_MEMINFO=/proc/meminfo", f"DDI_MEMINFO={shlex.quote(str(meminfo))}"
    )
    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd not installed")
def test_installer_space_preflight_uses_the_zstd_frame_header(
    tmp_path: Path, installer_wrapper: str
) -> None:
    block = _space_preflight_block(installer_wrapper)

    raw = tmp_path / "ddi.raw"
    raw.write_bytes(b"\0" * (3 * 1048576 + 1))
    subprocess.run(["zstd", "-q", "-f", str(raw), "-o", str(tmp_path / "ddi.raw.zst")], check=True)
    payload = (tmp_path / "ddi.raw.zst").read_bytes()

    # A frame that records a raw size of 3 MiB + 1 byte needs 3073 KiB: it passes
    # with that much free and fails with 3072 KiB (exactly 3 MiB), regardless of
    # the compressed size. The message rounds up to whole MiB and names both
    # bounds.
    ok = _run_space_preflight(tmp_path / "ok", block, payload, avail_kib=3 * 1024 + 1)
    assert ok.returncode == 0, ok.stderr
    assert "WARN" not in ok.stderr
    short = _run_space_preflight(tmp_path / "short", block, payload, avail_kib=3 * 1024)
    assert short.returncode == 1
    assert "need ~4 MiB; tmpfs has 3 MiB free, MemAvailable is 65536 MiB" in short.stderr


@pytest.mark.skipif(shutil.which("zstd") is None, reason="zstd not installed")
def test_installer_space_preflight_is_bounded_by_mem_available(
    tmp_path: Path, installer_wrapper: str
) -> None:
    block = _space_preflight_block(installer_wrapper)

    raw = tmp_path / "ddi.raw"
    raw.write_bytes(b"\0" * (3 * 1048576 + 1))
    subprocess.run(["zstd", "-q", "-f", str(raw), "-o", str(tmp_path / "ddi.raw.zst")], check=True)
    payload = (tmp_path / "ddi.raw.zst").read_bytes()

    # The tmpfs cap is generous but real memory is not: the rootfs is its own
    # tmpfs, so df on /dev/shm can report far more than the kernel can back.
    # MemAvailable minus 256 MiB headroom must also cover the raw image.
    headroom = 256 * 1024
    ok = _run_space_preflight(
        tmp_path / "ok", block, payload, avail_kib=1 << 30, mem_available_kib=headroom + 3 * 1024 + 1
    )
    assert ok.returncode == 0, ok.stderr
    short = _run_space_preflight(
        tmp_path / "short", block, payload, avail_kib=1 << 30, mem_available_kib=headroom + 3 * 1024
    )
    assert short.returncode == 1
    assert "need ~4 MiB; tmpfs has 1048576 MiB free, MemAvailable is 259 MiB" in short.stderr

    # A meminfo without a MemAvailable line fails closed too.
    broken = _run_space_preflight(
        tmp_path / "broken", block, payload, avail_kib=1 << 30, meminfo_text="MemTotal: 1 kB\n"
    )
    assert broken.returncode == 1
    assert "could not read MemAvailable" in broken.stderr


def test_installer_space_preflight_falls_back_to_five_times_compressed(
    tmp_path: Path, installer_wrapper: str
) -> None:
    block = _space_preflight_block(installer_wrapper)

    # Not a zstd frame: no header size, so 5x the 1 MiB file must fit, and the
    # wrapper says so.
    payload = b"x" * 1048576
    ok = _run_space_preflight(tmp_path / "ok", block, payload, avail_kib=5 * 1024)
    assert ok.returncode == 0, ok.stderr
    assert "WARN: zstd frame header carries no content size" in ok.stderr
    short = _run_space_preflight(tmp_path / "short", block, payload, avail_kib=5 * 1024 - 1)
    assert short.returncode == 1
    assert "need ~5 MiB; tmpfs has 4 MiB free" in short.stderr


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
