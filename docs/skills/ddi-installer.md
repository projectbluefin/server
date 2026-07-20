---
name: ddi-installer
description: Use when building or debugging the Bluefin Server DDI live installer, or managing the systemd-sysinstall recipes or target boot configurations.
metadata:
  type: reference
  status: stable
  last_updated: 2026-07-20
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---
# DDI Installer

## When to Use

- Building or debugging the Bluefin Server live installer media.
- Writing or refining `systemd-repart`, `bootctl`, or `ukify` configurations.
- Packaging or publishing DDI assets to GitHub Releases.
- Managing partition recipes for the target disk layout (`10-esp.conf`,
  `20-root-a.conf`, `30-var.conf`).

## When NOT to Use

- OCI-only image work (no installer involvement).
- Bootc-specific changes.
- Desktop or nspawn machine image work.
- Adding a network-pull installer — the design is offline; the DDI is embedded as
  a data partition.

## Architecture

The installer is offline, self-contained, and systemd-native. The OS DDI payload
(`bluefin-server-ddi.bst`) is embedded as a data partition on the installer
media at build time. No network access is required at install time.

The installer UI is systemd's built-in `systemd-sysinstall` which provides a
terminal-based interactive installation that:

- Prompts for the target disk (selected interactively or on the command line).
- Validates target disk size and suitability.
- Offers to erase the target disk or install alongside existing partitions.
- Copies the OS filesystem DDI block-for-block using `systemd-repart` and
  partition recipes (`CopyBlocks=`).
- Registers the bootloader (`systemd-boot`) and the Unified Kernel Image (UKI)
  using `bootctl`.
- Propagates installer environment settings (locale, keymap, timezone) to the
  target OS via encrypted credentials.
- Reboots into the installed system.

User provisioning is handled on the target system's first boot via systemd
system credentials (`systemd-sysusers`, `systemd-tmpfiles`) so the base image
remains stateless.

## Core Process

1. Keep the live media thin; orchestrate install-time flow with native systemd
   utilities.
2. The live environment boots with `systemd.unit=system-install.target` as a
   kernel command-line option.
3. systemd isolates `system-install.target` and starts
   `systemd-sysinstall.service` directly on `/dev/console` (tty0).
4. The live image overrides that service to run `/usr/bin/bluefin-sysinstall`,
   which calls `systemd-sysinstall` with the target OS UKI at
   `/usr/lib/bluefin-server/bluefin-server.efi` so `bootctl link` installs the
   target UKI instead of the installer UKI.
5. `systemd-sysinstall` reads partition recipes from
   `/usr/lib/repart.sysinstall.d/` if it is populated; otherwise it falls back
   to `/usr/lib/repart.d/`. The target recipes are staged at
   `/usr/lib/repart.d/` (`10-esp.conf`, `20-root-a.conf`, `30-var.conf`).
6. `20-root-a.conf` copies the DDI block-for-block from
   `/dev/disk/by-partlabel/bluefin-installer-data` (the embedded DDI data
   partition on the installer media).
7. Target OS volume expansion is handled by `systemd-growfs`; the target OS
   stack includes `xfsprogs` so the root and `/var` filesystems can grow to fill
   their partitions on first boot.

## Partition Layout

### Installer media (the USB/raw disk image)

| Partition | Type | Size | Contents |
|---|---|---|---|
| ESP | vfat | 1 GiB fixed | `EFI/BOOT/BOOTX64.EFI` + `EFI/Linux/installer.efi` (UKI) |
| `bluefin-installer-data` | XFS | auto | OS filesystem DDI image, copied block-for-block |

### Target disk (after install)

| Partition | Type | Size | Contents |
|---|---|---|---|
| ESP | vfat | 500 MiB – 1 GiB | `systemd-boot` + target OS UKI (`bluefin-server.efi`) |
| `bluefin-server-root-a` | XFS | 4 GiB – 16 GiB | OS root filesystem (copied from installer data partition) |
| `var` | XFS | ≥ 4 GiB | Writable persistent `/var`; grows to fill remaining disk |

## Installer Boot Flow

```text
UEFI reads ESP → BOOTX64.EFI → installer.efi (UKI)
     │
     ▼
systemd PID 1 starts, reaches system-install.target
     │
     ▼
systemd-sysinstall.service
     │
     ▼
bluefin-sysinstall wrapper
     ├─ Read /proc/cmdline for "unattended"
     ├─► [INTERACTIVE Mode]
     └─► [UNATTENDED Mode]
```

The reference installer element currently bakes `unattended` into the installer
UKI command line so headless tests can run without a human. To use the
interactive TUI, remove `unattended` from the UKI `--cmdline` in the installer
build element or invoke `systemd-sysinstall` directly on the console.

## Initrd Assembly (cpio-native)

`bluefin-server-installer.bst` assembles the live installer media inline. The
critical constraint is that the DDI is decompressed into `/layer` after the cpio
step; otherwise it would make the initrd several gigabytes or larger and
unbootable.

This is the gist of the process:

1. Create `/init` and set `default.target` to `system-install.target`.
2. Pack the early rootfs as newc cpio + gzip.
3. Decompress the DDI into `/layer` after cpio creation.
4. Build the installer UKI from the staged rootfs.
5. Assemble the GPT disk image with an ESP partition and the embedded DDI data
   partition using `systemd-repart`.

## Build and release details

For the detailed build/export/flash/release workflow, see
[ddi-installer-build.md](ddi-installer-build.md).

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

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] No `installer-knuckle.bst` or custom installer service units exist in the
      codebase.
- [ ] UKI boot cmdline points to `systemd.unit=system-install.target`.
- [ ] Serial console `console=ttyS0,115200` is the final console argument in the
      installer UKI cmdline.
- [ ] `installer-stack.bst` explicitly includes XFS and vfat support.
- [ ] `bluefin-server-installer.bst` overrides `systemd-sysinstall.service`
      with `SuccessAction=poweroff`/`FailureAction=poweroff` for clean shutdown.
- [ ] `bluefin-server-installer.bst` decompresses the DDI after the cpio step.
- [ ] `files/installer/repart.d/20-root-a.conf` has `GrowFileSystem=yes`.

## See also

- [ddi-installer-build.md](ddi-installer-build.md)
- `systemd-sysinstall(8)`, `systemd-sysinstall.service(8)`
- `systemd-repart(8)`, `repart.d(5)`
- `bootctl(1)`, `ukify(1)`
- `systemd-growfs(8)`
