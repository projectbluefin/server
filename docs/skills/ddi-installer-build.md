---
name: ddi-installer-build
description: Build, export, flash, and release the Bluefin Server installer media and DDI payload.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-09-04
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---
# DDI Installer Build and Release

Use this skill when you need to build the installer or DDI artifacts, export them,
flash them to media, or understand the release automation.

## When to Use

- Building or exporting the installer, DDI, or sysext artifacts locally or on the cluster.
- Flashing installer media to a USB device.
- Understanding or extending the release automation in `build.yml`.

## When NOT to Use

- Installer architecture, partition layout, or boot-flow questions — see
  [ddi-installer.md](ddi-installer.md).
- SBOM generation or release signing details — see
  [signing-and-sbom.md](signing-and-sbom.md).

## Build targets

The repo exposes the main build entrypoints through `just`:

```bash
just validate              # resolve the BuildStream graph
just build-installer       # build the installer locally
just export-installer      # export installer + UKI + SHA256SUMS to dist/
just build-ddi             # build the OS DDI payload
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
just build-sysext          # build the k3s sysext
just export-sysext         # export sysext artifacts to dist/sysext/
just flash-installer       # write the installer image to a USB device
just test                  # end-to-end local QEMU/KVM installer boot test
just tags                  # show FSDK-derived version tags
```

## Core Process

Run the local installer-to-boot acceptance path with:

```bash
just test
```

It builds and exports the installer, then boots the existing UEFI raw image in
QEMU/KVM. The test does not need a lab and keeps serial diagnostics when it
fails. It requires `qemu-system-x86_64`, readable `/dev/kvm`, `zstd`, and
`podman`. When host OVMF paths are not supplied, the harness stages the UEFI
code and variable-store template from the same cached `bst2` image used to
build the installer. Set both `OVMF_CODE` and `OVMF_VARS` to override that
source.

## Flashing the installer media

The installer is distributed as a UEFI-bootable raw GPT disk image (`.raw`)
that can be written directly to a USB drive.

### Recommended: `just flash-installer`

```bash
just flash-installer /dev/sdX
```

The wrapper validates the image, lists devices if you omit one, asks for
confirmation, and writes the image with direct I/O and an explicit sync.

### Manual `dd` flashing

```bash
sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst \
  | dd of=/dev/sdX bs=4M iflag=fullblock oflag=direct status=progress conv=fsync'
```

Use direct I/O and full-block reads to avoid dirtying the page cache.

## Release automation

The release process is driven by `.github/workflows/build.yml`:

- Renovate point-release updates or direct pushes to `main` trigger a full build.
- CI builds the DDI payload, installer, target UKI, and k3s sysext.
- CI uploads the versioned release assets to the corresponding
  `bluefin-server-v<release-version>` GitHub Release.
- CI also produces a combined `dist/release/SHA256SUMS` manifest and signs it
  to create `SHA256SUMS.gpg` for `systemd-sysupdate` verification.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot run the systemd-native interactive installer TUI. Use `systemd-sysinstall`. |
| "Use knuckle instead." | knuckle is deprecated in favor of native `systemd-sysinstall` (systemd 261+). |
| "Hardcode `root=/dev/vda2` for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "Pull the DDI from the network at install time." | Network failures = broken installs. The DDI is embedded in the installer media. |
| "Put the DDI in the initrd cpio." | The DDI is 2 GiB+. The initrd cpio step must run before the DDI is placed in `/layer`. |
| "Store the DDI in the ESP (FAT32)." | FAT32 has a 4 GiB per-file limit. Use a separate XFS partition. |
| "Add an 8 GiB minimum size floor to the DDI." | The rootfs is immutable. It never grows in-place. Content + overhead is enough. |

## Red Flags

- `systemd-sysinstall.service` is missing from `system-install.target.wants`.
- Boot cmdline uses a hardcoded device path like `root=/dev/vda2`.
- DDI decompression is placed before the cpio step.
- The installer data partition uses FAT32/vfat instead of XFS.
- The repart recipe is missing `GrowFileSystem=yes` for the copied rootfs.
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
- [ ] `files/installer/repart.d/20-root-a.conf` has `GrowFileSystem=yes`.
