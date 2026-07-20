---
name: ddi-installer-build
description: Build, export, flash, and release the Bluefin Server installer media and DDI payload.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-07-20
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
just build-ddi             # build the OS DDI payload
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
just build-sysext          # build the k3s sysext
just export-sysext         # export sysext artifacts to dist/sysext/
just flash-installer       # write the installer image to a USB device
just show-me-the-future    # end-to-end QEMU installer smoke test
just tags                  # show FSDK-derived version tags
```

## Preferred build path

For heavy builds, prefer the cluster build over a local workstation build:

```bash
just cluster-build
```

This submits the `bluefin-server-build-pipeline` Argo workflow and uses the
cluster cache rather than starving your local machine.

## Local builds with a remote cache

If you must build locally, point BuildStream at the cluster cache tunnel on
`ghost` by creating `~/.config/buildstream.conf` on your workstation:

```yaml
projects:
  bluefin-server:
    artifacts:
      override-project-caches: false
      servers:
      - url: grpc://127.0.0.1:8980
        push: true
```

Then run `just build-installer` or `just build-ddi`.

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
  `installer-v<release-version>` GitHub Release.
- CI also produces a combined `dist/release/SHA256SUMS` manifest and signs it
  to create `SHA256SUMS.gpg` for `systemd-sysupdate` verification.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot run the systemd-native interactive installer TUI. Use `systemd-sysinstall`. |
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
