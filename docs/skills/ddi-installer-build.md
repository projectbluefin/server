---
name: ddi-installer-build
description: Build, export, flash, and release the Bluefin Server installer media and DDI payload.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-08"
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---
# DDI Installer Build and Release

Use this skill when you need to build the installer or DDI artifacts, export them,
flash them to media, or understand the release automation.

## Build targets

The repo exposes the main build entrypoints through `just`:

```bash
just validate              # resolve the BuildStream graph
just cluster-build         # submit an Argo workflow to build/publish
just build-installer       # build the installer locally
just export-installer      # export installer + UKI + SHA256SUMS to dist/
just export-pxe            # export standalone PXE vmlinuz/initrd to dist/
just build-ddi             # build the OS DDI payload (see "Payload base" below)
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
just build-sysext          # build the k0s sysext
just export-sysext         # export sysext artifacts to dist/sysext/
just flash-installer       # write the installer image to a USB device
just show-me-the-future    # end-to-end QEMU installer smoke test
just test-installer-artifact # test already-exported artifacts in QEMU without rebuilding
just test-installer-boot-usb # test-installer-artifact in USB/firmware boot mode
just test-installer-boot-pxe # test-installer-artifact in PXE -kernel/-initrd boot mode
just tags                  # show FSDK-derived version tags
```

`just test-installer-artifact` boots the exported raw installer image through OVMF
firmware as an emulated xHCI USB drive (`-device qemu-xhci` plus `-device usb-storage`),
with the target disk on virtio-blk. This is the bare-metal USB install path: firmware
picks the bootloader off the image itself rather than QEMU injecting a kernel through
`-kernel`/`-initrd`. The boot method is selected by `INSTALLER_BOOT_MODE` (`usb`, the
default, or `pxe`); everything after the install is identical for both. `just
test-installer-boot-usb` and `just test-installer-boot-pxe` are the named entry points.

Use `pxe` mode to exercise the exported `bluefin-server-pxe-vmlinuz-*` /
`bluefin-server-pxe-initrd-*.cpio.gz` pair, which is booted with `-kernel`/`-initrd`
and an explicit `-append` command line. `just export-pxe` only asserts that those two
files exist, so the PXE recipe is what proves they still boot and install. PXE mode is
also the way to test an unattended install under Secure Boot firmware: in USB mode the
unattended flag travels via `-smbios type=11 io.systemd.stub.kernel-cmdline-extra`, and
systemd-stub ignores that credential when Secure Boot is enabled.

The recipe prefers a real `OVMF_VARS` template but falls back to a blank variable store
sized to `OVMF_CODE` on hosts that ship CODE only, so a missing template is a warning
rather than a hard failure. It needs `qemu-system-x86_64`, `zstd`, `sfdisk` and `jq` on
the host; the last two are used to assert that the installer actually partitioned the
target disk, and the recipe fails with a named error if either is missing.

### Payload base

`build-ddi` takes an optional `os-base` argument selecting which payload it
composes. It backs the FSDK-vs-Flatcar parity harness
(projectbluefin/server#129), where the two bases are built and compared:

```bash
just build-ddi                    # os-base=fsdk (default)
just build-ddi fsdk               # FSDK-composed payload -- the shipped base
just build-ddi flatcar-reference  # imported Flatcar reference tree -- the control
```

`flatcar-reference` routes to `oci/bluefin-server-ddi-flatcar-reference.bst`.
That element arrives with the imported Flatcar reference tree
(projectbluefin/server#126); until it does, `build-ddi flatcar-reference`
refuses with a message naming #126 rather than building anything. Anything
other than these two values is rejected.

`export-ddi` always exports the default `fsdk` payload -- it does not forward
`os-base`, so the reference tree is a comparison input, never a release
artifact.

## Mandatory build path: ghost cluster

This project MUST always build on the ghost cluster using distributed BuildStream:

```bash
just cluster-build
```

This submits the `bluefin-server-build-pipeline` Argo workflow to the ghost cluster and uses the
distributed cluster cache rather than building standalone OS artifacts locally on individual workstations.
## Local builds with a remote cache

If you must build locally, point BuildStream at your cluster cache tunnel host (`<build-cache-host>`) by creating `~/.config/buildstream.conf` on your workstation. Operators must substitute `<build-cache-host>` with their specific cluster cache hostname or IP when setting up the SSH tunnel (e.g. `ssh -L 8980:<build-cache-host>:8980 ...`):

```yaml
projects:
  bluefin-server:
    artifacts:
      override-project-caches: false
      servers:
      - url: grpc://127.0.0.1:8980
        push: true
```

Then run `just build-installer` or `just build-ddi` (add `flatcar-reference` to
build the parity-harness control instead of the shipped payload).

## Flashing the installer media

The installer is distributed as a UEFI-bootable raw GPT disk image (`.raw`)
that can be written directly to a USB drive.

### Recommended: `just flash-installer`

```bash
just flash-installer /dev/sdX
```

The wrapper validates the image, lists devices if you omit one, refuses a
device that backs the running system or has mounted partitions, requires
exactly one installer image in `dist/`, asks for confirmation, writes the
image with direct I/O and an explicit sync, verifies the written bytes by
sha256 readback, relocates the GPT backup header to the end of the device,
and confirms the `bluefin-installer-data` partition is present.

### Manual `dd` flashing

```bash
sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst \
  | dd of=/dev/sdX bs=4M iflag=fullblock oflag=direct status=progress conv=fsync'
```

Use direct I/O and full-block reads to avoid dirtying the page cache.

## Release automation

The release process is driven by `.github/workflows/build.yml`:

- Renovate point-release updates or direct pushes to `main` trigger a full build.
- CI builds the DDI payload, installer, target UKI, k0s sysext, and standalone
  PXE boot inputs (`bluefin-server-pxe-vmlinuz-*`, `bluefin-server-pxe-initrd-*.cpio.gz`).
- CI uploads the versioned release assets to the corresponding
  `installer-v<installer-version>` GitHub Release. The release tag tracks the
  installer axis, while the DDI and UKI inside it track the Flatcar payload axis (`flatcar-version`).
- CI also produces a combined `dist/release/SHA256SUMS` manifest and signs it
  to create `SHA256SUMS.gpg` for `systemd-sysupdate` verification. The PXE
  inputs are included in this manifest, per `docs/skills/ddi-installer.md`.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot run the systemd-native interactive installer TUI. Use `systemd-sysinstall`. |
| "Kernel image is at `/boot/vmlinuz`." | FSDK installs kernels into `/usr/lib/modules/<kver>/vmlinuz`. Toolchains (dracut, ukify, PXE export) must point to `/usr/lib/modules/<kver>/vmlinuz`. |
| "Initrd archive tools (gzip, cpio) are in base-stack." | In FSDK 26.08, gzip and cpio are standalone components; elements packing or unpacking initrds must explicitly declare `components/gzip.bst` and `components/cpio.bst` in `build-depends`. |
| "Use knuckle instead." | knuckle is deprecated in favor of native `systemd-sysinstall` (systemd 261+). |
| "Hardcode `root=/dev/vda2` for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "Pull the DDI from the network at install time." | Network failures = broken installs. The DDI is embedded in the installer media. |
| "Put the DDI in the initrd cpio." | The DDI is 2 GiB+. The initrd cpio step must run before the DDI is placed in `/layer`. |
| "Store the DDI in the ESP (FAT32)." | FAT32 has a 4 GiB per-file limit. Use a separate XFS partition. |
| "Add an 8 GiB minimum size floor to the DDI." | The rootfs is immutable. It never grows in-place. Content + overhead is enough. |

## Red flags

- `systemd-sysinstall.service` is missing from `system-install.target.wants`.
- Boot cmdline uses a hardcoded device path like `root=/dev/vda2`.
- DDI decompression is placed before the cpio step.
- The installer data partition uses FAT32/vfat instead of XFS.
- The repart recipe is missing `GrowFileSystem=no` for the copied rootfs.
- Unattended target-disk discovery is not filtered and can select empty devices.

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] No `installer-knuckle.bst` or custom installer service units exist.
- [ ] UKI boot cmdline points to `systemd.unit=system-install.target`.
- [ ] Serial console `console=ttyS0,115200` is the final console argument.
- [ ] `installer-stack.bst` explicitly includes XFS and vfat support.
- [ ] `bluefin-server-installer.bst` asserts the existence of critical tools
      (`udevadm`, `lsblk`, `systemd-repart`, `bootctl`, `systemd-sysinstall`).
- [ ] The live installer does not bake hardcoded SSH keys or pre-hashed root
      passwords.
- [ ] The DDI is decompressed after the cpio step.
- [ ] `files/installer/repart.d/20-root-a.conf` has `GrowFileSystem=no`.

## See also

- [ddi-installer.md](ddi-installer.md) — installer architecture and repart configuration.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (OS DDI, Installer terminology).
