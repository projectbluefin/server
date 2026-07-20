---
name: ddi-installer
description: "Use when building or debugging the Bluefin Server DDI live installer, or managing the systemd-sysinstall recipes or target boot configurations."
metadata:
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

The installer is **offline, self-contained, and systemd-native**. The OS DDI
payload (`bluefin-server-ddi.bst`) is embedded as a data partition on the
installer media at build time. No network access is required at install time.

The installer UI is systemd's built-in **systemd-sysinstall** (added in systemd
261.1) which provides a terminal-based interactive installation that:

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
   `/usr/lib/repart.sysinstall.d/` **if it is populated**; otherwise it falls
   back to `/usr/lib/repart.d/`. We stage target recipes at
   `/usr/lib/repart.d/` (`10-esp.conf`, `20-root-a.conf`, `30-var.conf`).
6. `20-root-a.conf` copies the DDI block-for-block from
   `/dev/disk/by-partlabel/bluefin-installer-data` (the embedded DDI data
   partition on the installer media).
7. Target OS volume expansion: the root and `/var` filesystems are marked with
   the Grow-File-System GPT flag (`GrowFileSystem=yes`) and grow to fill their
   partitions on first boot via `systemd-growfs`. The target OS stack
   (`elements/bluefin-server/os-stack.bst`) includes
   `freedesktop-sdk.bst:components/xfsprogs.bst` (the `xfs_growfs` backend).

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

```
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
     │
     ├─► [INTERACTIVE Mode]
     │     systemd-sysinstall \
     │       --kernel=/usr/lib/bluefin-server/bluefin-server.efi \
     │       --variables=yes \
     │       --reboot=yes \
     │       --mute-console=yes \
     │       --copy-locale=yes \
     │       --copy-keymap=yes \
     │       --copy-timezone=yes
     │       ├─ Interactive TUI: disk selection
     │       ├─ Interactive TUI: confirm installation summary
     │       └─ Locale/keymap/timezone propagated via encrypted credentials
     │
     └─► [UNATTENDED Mode]
           systemd-sysinstall \
             --kernel=/usr/lib/bluefin-server/bluefin-server.efi \
             --erase=yes \
             --confirm=no \
             --summary=no \
             --variables=yes \
             --reboot=no \
             --mute-console=yes \
             <TARGET_DISK>
             ├─ Automated disk selection and partitioning
             └─ No prompts or summary screens
     │
     ▼
systemd-repart --dry-run=no /dev/TARGET
     reads /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     20-root-a: CopyBlocks=/dev/disk/by-partlabel/bluefin-installer-data
     │
     ▼
bootctl link   (installs bluefin-server.efi to ESP)
     │
     ▼
bootctl install   (installs systemd-boot to ESP)
     │
     ▼
Reboot / poweroff into installed Bluefin Server
```

### Note on unattended vs interactive

The reference installer element (`elements/oci/bluefin-server-installer.bst`)
currently bakes `unattended` into the installer UKI command line so that the
headless QEMU test target (`just show-me-the-future`) runs without human input.
To use the interactive TUI, remove `unattended` from the UKI `--cmdline` in that
element, or invoke `systemd-sysinstall` directly on the console.

In unattended mode the wrapper passes `--reboot=no` and relies on
`SuccessAction=poweroff`/`FailureAction=poweroff` in the
`systemd-sysinstall.service` override so the installer VM shuts down cleanly
after installation completes.

## Initrd Assembly (cpio-native)

`bluefin-server-installer.bst` builds the installer media inline.

**Key constraint:** the DDI is decompressed into `/layer` **after** the cpio
step so it is not packed into the initrd (which would make it several gigabytes
or larger and unbootable).

```bash
# 1. /init symlink (Linux initrd protocol)
ln -sf usr/lib/systemd/systemd /layer/init

# 2. Link default.target -> system-install.target
ln -sf system-install.target /layer/usr/lib/systemd/system/default.target

# 3. Pack rootfs as newc cpio + gzip (DDI not yet in /layer)
( cd /layer && find . -print0 | cpio --null --create --format=newc ) \
  | gzip -9 -c > /installer.cpio.gz

# 4. Build the installer UKI.
#    The cmdline includes "unattended" for headless testing.
ukify build \
  --linux="/layer/boot/vmlinuz" \
  --initrd=/installer.cpio.gz \
  --cmdline="systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended" \
  --output=/layer/boot/efi/EFI/BOOT/BOOTX64.EFI

# 5. Decompress DDI into /layer AFTER cpio (won't be in initrd)
zstd -d /ddi/bluefin-server-ddi-*.raw.zst -o /layer/bluefin-server-ddi.raw

# 6. Assemble two-partition GPT disk (ESP + data partition with DDI)
#    CopyBlocks= in repart resolves paths under --root=/layer
systemd-repart --empty=create --size=auto --dry-run=no \
  --root=/layer --definitions=/installer-media-repart.d \
  bluefin-server-installer-<ver>.raw

# 7. Clean up DDI from /layer (now embedded in installer media)
rm -f /layer/bluefin-server-ddi.raw
```

The installer media data partition repart config used above is:

```ini
[Partition]
Type=esp
Format=vfat
CopyFiles=/boot/efi:/
SizeMinBytes=1024M
SizeMaxBytes=1024M
```

```ini
[Partition]
Type=linux-generic
Label=bluefin-installer-data
CopyBlocks=/bluefin-server-ddi.raw
```

## OS DDI Payload

`oci/bluefin-server-ddi.bst` builds the OS DDI payload:

1. Depends on `bluefin-server/os-stack.bst` (must include
   `freedesktop-sdk.bst:components/xfsprogs.bst` for target XFS expansion).
2. Strips debug files.
3. Sums actual file sizes across bind mounts using `du -sb`.
4. Adds 25% overhead + 100 MiB margin for XFS metadata/journal.
5. Aligns filesystem size to 4096-byte sectors.
6. Pre-allocates the raw file with `truncate -s`.
7. Populates it with `mkfs.xfs -f -L bluefin-root -p /layer`.
8. Compresses with `zstd` → `bluefin-server-ddi-@v.raw.zst` + `SHA256SUMS`.

**No minimum size floor.** The rootfs is immutable — updates replace the whole
DDI, it never grows in-place.

## Justfile Commands

```
just validate              # resolve element graph
just cluster-build         # submit build to the cluster using Argo
just build-installer       # build installer locally
just export-installer      # export .raw.zst + UKI + SHA256SUMS to dist/
just build-ddi             # build OS DDI filesystem payload
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
just build-sysext          # build k3s systemd-sysext
just export-sysext         # export sysext artifacts to dist/sysext/
just flash-installer       # write the installer image to a USB device
just show-me-the-future    # end-to-end QEMU installer smoke test
just tags                  # show FSDK-derived version tags
```

### Building on the cluster (preferred)

To prevent resource starvation on your local workstation, delegate heavy
BuildStream builds to the cluster:

```bash
just cluster-build
```

This submits an Argo workflow `bluefin-server-build-pipeline` to build and
publish the latest installer/DDI to the local registry.

### Local builds with remote cache (alternative)

If you must run a local build, configure the BuildStream remote cache on `ghost`
using the local tunnel. Create `~/.config/buildstream.conf` on your workstation:

```yaml
projects:
  bluefin-server:
    artifacts:
      override-project-caches: false
      servers:
      - url: grpc://127.0.0.1:8980
        push: true
```

Then run `just build-installer` or `just build-ddi`. This pulls pre-built
layers from the cluster's CAS cache over localhost port 8980.

## Flashing the Installer Media

Modern systemd installer design (UAPI and systemd-repart) discourages legacy ISO
files in favor of **UEFI-bootable raw GPT disk images** (`.raw`). These can be
written directly to a USB drive and boot natively under UEFI.

### Recommended: `just flash-installer`

Run the native flashing target with your USB block device. It validates the
image, lists devices if you omit one, asks for confirmation, and uses direct I/O
with full-block reads and an explicit sync:

```bash
just flash-installer /dev/sdX
```

### Manual `dd` flashing

When writing the exported `.raw.zst` installer image to a physical USB drive, use
direct I/O to avoid dirtying the host page cache, and ensure full-block reads
from the decompressor:

```bash
sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst \
  | dd of=/dev/sdX bs=4M iflag=fullblock oflag=direct status=progress conv=fsync'
```

## Release

The release process is fully automated via `.github/workflows/build.yml`:

- When Renovate merges a point-release update to `main` (or a direct push is made
  to `main`), GitHub Actions triggers a full compile.
- CI builds the standalone DDI OS image, live installer, target UKI, and k3s
  sysext using `/mnt` SSD storage, then creates a new GitHub Release with the
  versioned tag `installer-v<release-version>` (e.g. `installer-v25.08.14`).
- All compiled binaries (zstd-compressed installer raw images, standalone DDI
  payloads, EFI binaries, k3s sysext, and SHA256 checksums) are uploaded directly
  to the GitHub Release.
- The release process also produces a single combined `dist/release/SHA256SUMS`
  manifest and signs it with the `SYSUPDATE_SIGNING_KEY` to produce
  `SHA256SUMS.gpg` for `systemd-sysupdate` verification.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot run the systemd-native interactive installer TUI. Use `systemd-sysinstall`. |
| "Use knuckle instead." | knuckle is deprecated in favor of native `systemd-sysinstall` (systemd 261+). |
| "Hardcode `root=/dev/vda2` for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "Pull the DDI from the network at install time." | Network failures = broken installs. The DDI is embedded in the installer media. |
| "Put the DDI in the initrd cpio." | The DDI is 2 GiB+. The initrd cpio step must run **before** the DDI is placed in `/layer`. |
| "Store the DDI in the ESP (FAT32)." | FAT32 has a 4 GiB per-file limit. Use a separate XFS partition. |
| "Add an 8 GiB minimum size floor to the DDI." | The rootfs is immutable. It never grows in-place. Content + overhead is enough. |

## Red Flags

- `systemd-sysinstall.service` is missing from `system-install.target.wants`.
- Boot cmdline has `root=/dev/vda2` (hardcoded device path).
- DDI decompression step placed **before** the cpio step (DDI ends up in the
  initrd).
- Data partition uses FAT32/vfat (4 GiB file limit — the DDI might not fit).
- `files/installer/repart.d/20-root-a.conf` missing `GrowFileSystem=yes` (causes
  filesystem capacity mismatches on larger disks).
- VM target disk uses a static capacity in a test script, hiding dynamic
  resizing/repart crashes.
- Unattended target-disk discovery is unfiltered, allowing empty or read-only
  devices like `/dev/sr0` to be selected.

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] No `installer-knuckle.bst` or custom installer service units exist in the
  codebase.
- [ ] UKI boot cmdline points to `systemd.unit=system-install.target`.
- [ ] Serial console `console=ttyS0,115200` is the final console argument in the
  installer UKI cmdline for clean serial redirection.
- [ ] `installer-stack.bst` explicitly includes XFS and vfat support.
- [ ] `bluefin-server-installer.bst` asserts the existence of critical tools
  (`udevadm`, `lsblk`, `systemd-repart`, `bootctl`, `systemd-sysinstall`) at
  build time.
- [ ] `bluefin-server-installer.bst` installs `/usr/bin/bluefin-sysinstall`
  wrapper that handles locale/keymap/timezone copy flags and unattended mode,
  with disk auto-discovery filtering (`type=disk`, read-only=0, size>0).
- [ ] The live installer does not bake hardcoded SSH keys or pre-hashed root
  passwords.
- [ ] `bluefin-server-installer.bst` builds `/usr/lib/bluefin-server/bluefin-server.efi`
  from a staged target rootfs with dracut + ukify.
- [ ] `bluefin-server-installer.bst` overrides `systemd-sysinstall.service`
  with `SuccessAction=poweroff`/`FailureAction=poweroff` for clean shutdown in
  headless test environments.
- [ ] `bluefin-server-installer.bst` decompresses the DDI **after** the cpio
  step.
- [ ] `bluefin-server-ddi.bst` sizes the filesystem at content + overhead (no
  hardcoded floor).
- [ ] `files/installer/repart.d/20-root-a.conf` has `GrowFileSystem=yes` to
  expand the copied root filesystem.
- [ ] Target OS stack `os-stack.bst` includes `xfsprogs.bst` for volume
  expansion at boot.

## See also

- `systemd-sysinstall(8)`, `systemd-sysinstall.service(8)`
- `systemd-repart(8)`, `repart.d(5)`
- `bootctl(1)`, `ukify(1)`
- `systemd-growfs(8)`
