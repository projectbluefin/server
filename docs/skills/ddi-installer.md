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

- Building or debugging the Bluefin Server live installer media
- Writing or refining `systemd-repart`, `bootctl`, or `ukify` configurations
- Packaging or publishing DDI assets to GitHub Releases
- Managing partition recipes for the target disk layout (`10-esp.conf`, `20-root-a.conf`, `30-var.conf`)

## When NOT to Use

- OCI-only image work (no installer involvement)
- Bootc-specific changes
- Desktop or nspawn machine image work
- Adding a network-pull installer — the design is offline, DDI embedded as a data partition

## Architecture

The installer is **offline, self-contained, and systemd-native**. The OS DDI payload (`bluefin-server-ddi.bst`) is embedded as a data partition on the installer media at build time. No network access is required at install time.

The installer UI is systemd's built-in **systemd-sysinstall** (introduced in systemd 261) which provides a clean, terminal-based interactive installation:

- Prompts the user for target disk (selected interactively or on CLI)
- Validates target disk size and suitability
- Offers to erase the target disk or install alongside existing partitions
- Copies the OS filesystem DDI block-for-block using `systemd-repart` and partition recipes (`CopyBlocks=`)
- Registers the bootloader (`systemd-boot`) and the Unified Kernel Image (UKI) using `bootctl`
- Securely encrypts and propagates installer environment credentials (locale, keymap, timezone) to the target OS
- Reboots into the installed system

User provisioning is handled on the target system's first boot via `systemd-firstboot` or other firstboot configurations, maintaining clean statelessness.

## Core Process

1. Keep the live media thin: orchestrate install-time flow via native systemd utilities.
2. The live environment boots with `systemd.unit=system-install.target` as a kernel command-line option.
3. Systemd isolates `system-install.target` and starts the `systemd-sysinstall.service` directly on `/dev/console` (tty0).
4. The live image overrides that service to execute `systemd-sysinstall --kernel=/usr/lib/bluefin-server/bluefin-server.efi --variables=yes --reboot=yes --mute-console=yes`, so `bootctl link` installs a target OS UKI instead of the installer UKI.
5. `bluefin-server-installer.bst` stages a second copy of the target OS rootfs during the installer build, runs `dracut` + `ukify` against it, and places the resulting `bluefin-server.efi` at `/usr/lib/bluefin-server/bluefin-server.efi` inside the live image.
6. `systemd-sysinstall` reads partition recipes from `/usr/lib/repart.d/` (falling back automatically since `/usr/lib/repart.sysinstall.d/` is empty).
7. The `20-root-a.conf` partition recipe copies the DDI block-for-block from `/dev/disk/by-partlabel/bluefin-installer-data` (which is the embedded DDI partition on the installer media).
8. Target OS volume expansion: `root-a` and `/var` partitions are resized to fill available space on boot using `systemd-growfs`. This requires the target OS stack (`elements/bluefin-server/os-stack.bst`) to include `freedesktop-sdk.bst:components/xfsprogs.bst` (providing the `xfs_growfs` tool).

## SSH access to live installer

The installer live environment runs `sshd.service` on `system-install.target`.
The live image adds an `sshd.service` drop-in that generates missing
`/etc/ssh/ssh_host_*` keys on first boot before `sshd` starts, so the service
can come up cleanly without depending on build-sandbox key generation.
Connect headlessly during install:

```
ssh root@<installer-ip>   # no password required
```

sshd config drop-in (`/etc/ssh/sshd_config.d/installer.conf`):
```
PermitRootLogin yes
PermitEmptyPasswords yes
```

Root has no password in the installer rootfs. Network comes up via DHCP on all `en*/eth*/ens*/enp*` interfaces. Find the IP from the console or your DHCP server's lease table.

## Partition Layout

The installer media is a two-partition GPT disk:

| Partition | Type | Size | Contents |
|---|---|---|---|
| ESP | vfat | 768M | `installer.efi` + `BOOTX64.EFI` (UKI) |
| `bluefin-installer-data` | XFS | 2.4G | OS filesystem DDI image (block copy) |

At install time, target partition `20-root-a.conf`'s `CopyBlocks=` copies blocks directly from `/dev/disk/by-partlabel/bluefin-installer-data`.

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
bluefin-sysinstall (wrapper script)
     ├─ Warn if TPM is absent (prevents insecure credential sealing fallback)
     ├─ Read /proc/cmdline for "unattended"
     │
     ├─► [INTERACTIVE Mode]
     │     systemd-sysinstall --kernel=/usr/lib/bluefin-server/bluefin-server.efi --variables=yes --reboot=yes --mute-console=yes --copy-locale=yes --copy-keymap=yes --copy-timezone=yes --load-credential=passwd.hashed-password.root:/etc/root_hash
     │       ├─ Interactive TUI: disk selection
     │       ├─ Interactive TUI: confirm installation summary
     │       ├─ Propagate locale, keymap, and timezone via systemd-creds
     │
     └─► [UNATTENDED Mode]
           systemd-sysinstall --kernel=/usr/lib/bluefin-server/bluefin-server.efi --variables=yes --reboot=yes --mute-console=yes --erase=yes --confirm=no --summary=no --load-credential=passwd.hashed-password.root:/etc/root_hash
             ├─ Automated disk selection and partitioning
             └─ No prompts or summary screens
     │
     ▼
systemd-repart --dry-run=no /dev/TARGET
     reads /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     20-root-a: CopyBlocks=/dev/disk/by-partlabel/bluefin-installer-data
     │
     ▼
bootctl link (installs bluefin-server.efi + secure hashed root credentials to ESP)
     │
     ▼
bootctl install (installs systemd-boot to ESP)
     │
     ▼
Reboot into installed Bluefin Server
```

## Initrd Assembly (cpio-native)

`bluefin-server-installer.bst` builds the installer media inline.
**Key constraint**: the DDI is decompressed into `/layer` AFTER the cpio step so it is not packed into the initrd (which would make it 8GB+).

```bash
# 1. /init symlink (Linux initrd protocol)
ln -sf usr/lib/systemd/systemd /layer/init

# 2. Link default.target -> system-install.target
ln -sf system-install.target /layer/usr/lib/systemd/system/default.target

# 3. Pack rootfs as newc cpio + zstd (DDI not yet in /layer)
( cd /layer && find . -print0 | cpio --null --create --format=newc ) \
  | zstd -T0 -19 -q -o /installer.cpio.zst

# 4. Build UKI
ukify build --linux="/layer/boot/vmlinuz" --initrd=/installer.cpio.zst \
  --cmdline="systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw" \
  --output=/layer/boot/efi/EFI/Linux/installer.efi

# 5. Decompress DDI into /layer AFTER cpio (won't be in initrd)
zstd -d /ddi/bluefin-server-ddi-*.raw.zst -o /layer/bluefin-server-ddi.raw

# 6. Assemble two-partition GPT disk (ESP + data partition with DDI)
#    CopyFiles= in repart resolves paths under --root=/layer
systemd-repart --empty=create --size=auto --dry-run=no \
  --root=/layer --definitions=/installer-media-repart.d \
  bluefin-server-installer-<ver>.raw

# 7. Clean up DDI from /layer (now embedded in installer media)
rm -f /layer/bluefin-server-ddi.raw
```

The installer media data partition repart config:

```ini
[Partition]
Type=linux-generic
Label=bluefin-installer-data
CopyBlocks=/bluefin-server-ddi.raw
```

## OS DDI Payload

`oci/bluefin-server-ddi.bst` builds the OS DDI payload:
1. Depends on `bluefin-server/os-stack.bst` (must include `freedesktop-sdk.bst:components/xfsprogs.bst` for Target XFS expansion).
2. Strips debug files
3. Sums up all file sizes across the layered sandbox bind mounts using find & pure bash arithmetic to bypass overlayfs block reporting bugs.
4. Align filesystem target size to 4096-byte sectors.
5. Pre-allocates the raw file using `truncate -s` (since mkfs.xfs ignores block size counts on regular files).
6. Runs `mkfs.xfs` on the pre-allocated file with 25% overhead and 100MB margin for XFS structures (no static floor).
7. Compresses with `zstd` → `bluefin-server-ddi-@v.raw.zst` + `SHA256SUMS`

**No minimum size floor.** The rootfs is immutable — updates replace the whole DDI, it never grows in-place. A typical server rootfs (~2GB content) produces a ~2.2GB DDI. Do not add a `SizeMinBytes` floor "for future growth" — that headroom is wasted.

## Justfile Commands

```
just validate-installer    # resolve element graph
just cluster-build         # submit build to the cluster using Argo (no workstation CPU/MEM usage)
just build-installer       # build installer locally (uses remote cache if configured)
just export-installer      # export .raw.zst + SHA256SUMS to dist/
just build-ddi             # build DDI standalone (for release publishing)
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
just show-me-the-future    # end-to-end QEMU test
```

### Building on the Cluster (Preferred)

To prevent resource starvation on your local workstation, delegate heavy BuildStream builds to the cluster. Run:

```bash
just cluster-build
```

This submits an Argo workflow `bluefin-server-build-pipeline` to the cluster to build and publish the latest installer/DDI to the local registry.

### Local Builds with Remote Cache (Alternative)

If you must run a local build, configure the BuildStream remote cache on `ghost` using the local tunnel. Create `~/.config/buildstream.conf` on your workstation:

```yaml
projects:
  bluefin-server:
    artifacts:
      override-project-caches: false
      servers:
      - url: grpc://127.0.0.1:8980
        push: true
```

Then run `just build` or `just build-installer`. This pulls pre-built layers from the cluster's Buildbarn CAS cache over localhost port 8980, accelerating builds to under 10 minutes.


## Flashing the Installer Media

When flashing the exported `.raw.zst` installer image to a physical USB drive (block devices like `/dev/sda`), do **not** use uncached, buffered `dd` writes.

### Dirty Page Cache Warning (USB Write Stalls)
By default, Linux's page cache buffers writes in host RAM. On slow USB media, this can dirty gigabytes of system memory, causing severe system-wide hangs and freezing your desktop environment while the kernel tries to flush the dirty buffer to the flash chips.

### The Fix (Direct I/O)
Bypass the kernel page cache entirely using **`oflag=direct`**. This writes blocks directly to the USB drive, keeping the desktop window and the system completely responsive. Ensure **`iflag=fullblock`** is used to avoid pipe alignment issues:

```bash
sudo sh -c 'zstd -dc dist/bluefin-server-installer-*.raw.zst | dd of=/dev/sda bs=4M iflag=fullblock oflag=direct status=progress'
```

## Release

`.github/workflows/release-installer.yml` fires on `installer-v*` tags.
**GitHub is the control plane only** — the workflow resolves the tag ref, runs `just validate-installer`, then publishes an `installer-build/<tag>` GitOps signal tag. The lab consumes that tag, builds, and uploads artifacts.

```bash
git tag installer-v25.08.13 && git push origin installer-v25.08.13
```

> No BST build compute runs on GitHub-hosted runners.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot prompt for credentials on a TTY. Use `systemd-sysinstall` natively. |
| "Use knuckle instead." | knuckle is deprecated in favor of native systemd-sysinstall (systemd v261+). |
| "Hardcode root=/dev/vda2 for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "Pull the DDI from the network at install time." | Network failures = broken installs. DDI must be embedded in the installer media. |
| "Put the DDI in the initrd cpio." | DDI is 2GB+. The initrd cpio step must run BEFORE the DDI is placed in /layer. |
| "Store DDI in the ESP (FAT32)." | FAT32 has a 4GB per-file limit. Use a separate XFS partition. |
| "Add an 8GB minimum size floor to the DDI." | The rootfs is immutable. It never grows in-place. Content + 10% overhead is enough. |

## Red Flags

- `systemd-sysinstall.service` is missing from system-install target wants
- Boot cmdline has `root=/dev/vda2` (hardcoded device path)
- DDI decompression step placed BEFORE the cpio step (DDI ends up in the initrd)
- Data partition uses FAT32/vfat (4GB file limit — DDI won't fit)
- `files/installer/repart.d/20-root-a.conf` missing `GrowFileSystem=yes` (causes filesystem capacity/sizing mismatches on larger disks)
- VM target disk in test script (`Justfile`) uses a static capacity (e.g., hardcoded `16G`), hiding dynamic resizing/repart crashes.
- Unattended target-disk discovery is unfiltered, allowing empty or read-only devices like `/dev/sr0` (optical drives) to be incorrectly chosen, leading to installation failure.

## Verification

- [ ] `just validate-installer` resolves the BuildStream graph without errors
- [ ] No `installer-knuckle.bst` or `installer.service` exists in the codebase
- [ ] UKI boot cmdline points to `systemd.unit=system-install.target`
- [ ] Serial console `console=ttyS0,115200` is the final console argument in UKI cmdline to ensure primary interactive `/dev/console` output redirects cleanly over headless QEMU serial (e.g. `mon:stdio` with `-nographic`), avoiding graphic-mode VGA curses limitations
- [ ] `installer-stack.bst` explicitly includes `gawk`, `sed`, `grep`, `xfsprogs`, and `openssh-systemd`
- [ ] `bluefin-server-installer.bst` asserts the existence of critical tools (`awk`, `gawk`, `sed`, `grep`, `udevadm`, `lsblk`, `systemd-repart`, `bootctl`, `systemd-sysinstall`, `sshd`) and `sshd.service` at build-time
- [ ] `bluefin-server-installer.bst` writes a secure pre-hashed root password (`/etc/root_hash`) and installs a centralized `/usr/bin/bluefin-sysinstall` wrapper script that handles TPM detection, explicit locale/keymap/timezone copy flags, and unattended mode triggering with disk auto-discovery filtering (type "disk", read-only=0, size>0) to ignore empty or optical drives
- [ ] `bluefin-server-installer.bst` installs an `sshd.service` drop-in that generates missing OpenSSH host keys on boot
- [ ] `bluefin-server-installer.bst` builds `/usr/lib/bluefin-server/bluefin-server.efi` from a staged target rootfs with dracut + ukify and overrides `systemd-sysinstall.service` to use it (configuring SuccessAction=poweroff and FailureAction=poweroff to ensure clean ACPI motherboard shutdown of the guest VM upon install completion, allowing test wrappers to proceed automatically)
- [ ] `bluefin-server-installer.bst` decompresses DDI AFTER the cpio step
- [ ] `bluefin-server-ddi.bst` sizes filesystem at content + 25% (no hardcoded floor)
- [ ] `files/installer/repart.d/20-root-a.conf` has `GrowFileSystem=yes` to expand the copied root filesystem
- [ ] Lab build template points at correct repo and installer element
- [ ] Target OS stack `os-stack.bst` includes `xfsprogs.bst` for volume expansion at boot
