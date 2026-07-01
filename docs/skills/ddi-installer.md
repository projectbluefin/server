---
name: ddi-installer
description: "Use when building or debugging the Bluefin Server DDI live installer, updating the knuckle installer binary, or working on the lab GitOps build hook."
metadata:
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---

# DDI Installer

## When to Use

- Building or debugging the Bluefin Server live installer media
- Bumping the knuckle installer binary version
- Wiring `systemd-repart`, `bootctl`, or `ukify`
- Packaging or publishing DDI assets to GitHub Releases
- Updating the Argo/GitOps build hook in the lab

## When NOT to Use

- OCI-only image work (no installer involvement)
- Bootc-specific changes
- Desktop or nspawn machine image work
- Adding a network-pull installer — the design is offline, DDI embedded as a data partition

## Architecture

The installer is **offline and self-contained**. The OS DDI payload
(`bluefin-server-ddi.bst`) is embedded as an ext4 data partition on the
installer media at build time. No network access is required at install time.

The installer UI is **knuckle** — a Go TUI interactive installer
(`projectbluefin/knuckle`) that prompts the user for:

- Target disk (detected via `lsblk`)
- Username, password (bcrypt-hashed), SSH key
- Confirmation before writing

Then it runs `systemd-repart`, provisions the user, writes a stable
`PARTUUID`-based boot entry via `bootctl`, and reboots.

**Why knuckle and not systemd-sysinstall?**
`systemd-sysinstall` requires systemd ≥261 (released June 2026) and does NOT
prompt for username/password — it defers to `systemd-firstboot` on first boot.
knuckle is already used for Flatcar/FCOS installs in this org, is tested, and
provides full user provisioning during install.

## Core Process

1. Keep the live media thin: orchestrate install-time flow via knuckle, not a second distro.
2. knuckle binary lives at `/opt/knuckle` in the installer rootfs — staged by `installer/installer-knuckle.bst`.
3. `installer.service` mounts the embedded DDI partition, then runs `/opt/knuckle --os bluefin-ddi` on `tty1`.
4. knuckle uses `PARTLABEL=bluefin-server-root-a` to find its root partition — never hardcode `/dev/vda2`.
5. Publish installer media as a single versioned release asset with matching checksum.
6. The lab GitOps pipeline clones the server repo and builds the installer element.
7. Use `just show-me-the-future` as the end-to-end VM test: boot installer, install to a second disk, reboot into installed system.

## Bumping the knuckle version

When a new knuckle release is cut:

```bash
# 1. Get the SHA256 of the new binary
SHA=$(curl -sL https://github.com/projectbluefin/knuckle/releases/download/vX.Y.Z/knuckle-linux-amd64 | sha256sum | awk '{print $1}')

# 2. Update elements/installer/installer-knuckle.bst
#    Change both `url:` (version in path) and `ref:` (sha256)
```

`installer-knuckle.bst` uses `kind: manual` with a `kind: remote` source
(BST verifies the sha256 on fetch). The script stages the binary at
`/opt/knuckle` with mode 755.

**Current version:** knuckle v0.9.0
**SHA256:** `ddaa1d67eb1422d76a1d1e2bc2fad3936b9da136f416d4da12c88f7311226693`

## SSH access to live installer

The installer live environment runs sshd. Connect headlessly during install:

```
ssh root@<installer-ip>   # no password required
```

sshd config drop-in (`/etc/ssh/sshd_config.d/installer.conf`):
```
PermitRootLogin yes
PermitEmptyPasswords yes
```

Root has no password in the installer rootfs. Network comes up via DHCP
on all `en*/eth*/ens*/enp*` interfaces. Find the IP from the console or
your DHCP server's lease table.



The installer media is a two-partition GPT disk:

| Partition | Type | Size | Contents |
|---|---|---|---|
| ESP | vfat | 1G | `installer.efi` + `BOOTX64.EFI` (UKI) |
| `bluefin-installer-data` | ext4 | 10–16G | `bluefin-server-ddi.raw` (OS filesystem image) |

At install time, `installer.service` mounts the data partition before knuckle
runs so `repart.d/20-root-a.conf`'s `CopyBlocks=` finds the DDI at
`/run/installer/bluefin-server-ddi.raw`.

## Installer boot flow

```
UEFI reads ESP → BOOTX64.EFI → installer.efi (UKI)
     │
     ▼
systemd PID 1 starts, reaches installer.target
     │
     ▼
installer.service
  ExecStartPre: modprobe nvme + udevadm settle
  ExecStartPre: mount /dev/disk/by-partlabel/bluefin-installer-data /run/installer
     │
     ▼
/opt/knuckle --os bluefin-ddi
     │
     ├─ TUI: disk selection (lsblk detects candidates)
     ├─ TUI: username / password / SSH key
     ├─ systemd-repart --dry-run=no /dev/TARGET
     │      reads /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     │      20-root-a: CopyBlocks=/run/installer/bluefin-server-ddi.raw
     ├─ User provisioning (useradd + authorized_keys + sudoers)
     ├─ bootctl install (PARTUUID boot entry)
     └─ Reboot into installed Bluefin Server
```

## Initrd assembly (cpio-native)

`bluefin-server-installer.bst` builds the installer media inline.
**Key constraint**: the DDI is decompressed into `/layer` AFTER the cpio step
so it is not packed into the initrd (which would make it 8GB+).

```bash
# 1. /init symlink (Linux initrd protocol)
ln -sf usr/lib/systemd/systemd /layer/init

# 2. Link default.target -> installer.target
ln -sf installer.target /layer/usr/lib/systemd/system/default.target

# 3. Pack rootfs as newc cpio + zstd (DDI not yet in /layer)
( cd /layer && find . -print0 | cpio --null --create --format=newc ) \
  | zstd -T0 -19 -q -o /installer.cpio.zst

# 4. Build UKI
ukify build --linux="/layer/boot/vmlinuz" --initrd=/installer.cpio.zst \
  --cmdline="systemd.unit=installer.target console=ttyS0,115200 rw" \
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

The data partition repart config:

```ini
[Partition]
Type=linux-generic
Label=bluefin-installer-data
CopyBlocks=/bluefin-server-ddi.raw
```

## OS DDI payload

`oci/bluefin-server-ddi.bst` builds the OS DDI payload:
1. Depends on `bluefin-server/os-stack.bst`
2. Strips debug files
3. Sums up all file sizes across the layered sandbox bind mounts using find & pure bash arithmetic to bypass overlayfs block reporting bugs.
4. Align filesystem target size to 4096-byte sectors.
5. Pre-allocates the raw file using `truncate -s` (since mkfs.ext4 ignores block size counts on regular files).
6. Runs `mkfs.ext4` on the pre-allocated file with 25% overhead and 100MB margin for ext4 structures (no static floor).
7. Compresses with `zstd` → `bluefin-server-ddi-@v.raw.zst` + `SHA256SUMS`

**No minimum size floor.** The rootfs is immutable — updates replace the whole DDI,
it never grows in-place. A typical server rootfs (~2GB content) produces a ~2.2GB
DDI. Do not add a `SizeMinBytes` floor "for future growth" — that headroom is wasted.

## Justfile commands

```
just validate-installer    # resolve element graph
just build-installer       # full build: cpio + ukify + systemd-repart (includes DDI)
just export-installer      # export .raw.zst + SHA256SUMS to dist/
just build-ddi             # build DDI standalone (for release publishing)
just export-ddi            # export DDI + SHA256SUMS to dist/ddi/
just show-me-the-future    # end-to-end QEMU test
```

## Release

`.github/workflows/release-installer.yml` fires on `installer-v*` tags.
**GitHub is the control plane only** — the workflow resolves the tag ref,
runs `just validate-installer`, then publishes an `installer-build/<tag>`
GitOps signal tag. The lab consumes that tag, builds, and uploads artifacts.

```bash
git tag installer-v0.1.0 && git push origin installer-v0.1.0
```

> No BST build compute runs on GitHub-hosted runners.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot prompt for username/password/SSH key. |
| "Use systemd-sysinstall instead." | Requires systemd ≥261 AND doesn't set username/password. knuckle is prod-tested. |
| "Hardcode root=/dev/vda2 for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "Pull the DDI from the network at install time." | Network failures = broken installs. DDI must be embedded in the installer media. |
| "Put the DDI in the initrd cpio." | DDI is 2GB+. The initrd cpio step must run BEFORE the DDI is placed in /layer. |
| "Store DDI in the ESP (FAT32)." | FAT32 has a 4GB per-file limit. Use a separate ext4 partition. |
| "Add an 8GB minimum size floor to the DDI." | The rootfs is immutable. It never grows in-place. Content + 10% overhead is enough. |
| "SuccessAction=poweroff in installer.service." | knuckle drives shutdown. Having both races. Remove from service. |

## Red Flags

- `installer.service` has `SuccessAction=poweroff` (knuckle handles this)
- `installer.service` `ExecStart` points at a bash script instead of `/opt/knuckle`
- `installer-knuckle.bst` `ref:` is a placeholder (`PLACEHOLDER_*`)
- Boot cmdline has `root=/dev/vda2` (hardcoded device path)
- knuckle binary is vendored in the repo instead of fetched from releases
- `installer-stack.bst` missing `installer/installer-knuckle.bst` dependency
- `installer-sysupdate.bst` present in `installer-stack.bst` (removed; DDI is embedded)
- DDI decompression step placed BEFORE the cpio step (DDI ends up in the initrd)
- Data partition uses FAT32/vfat (4GB file limit — DDI won't fit)

## Verification

- [ ] `just validate-installer` resolves the BuildStream graph without errors
- [ ] `installer-knuckle.bst` `ref:` matches `sha256sum` of the release binary
- [ ] `installer.service` `ExecStart=/opt/knuckle --os bluefin-ddi`
- [ ] `installer.service` mounts `/dev/disk/by-partlabel/bluefin-installer-data` to `/run/installer` before knuckle
- [ ] `installer.service` has NO `SuccessAction=poweroff`
- [ ] `installer-stack.bst` includes `installer/installer-knuckle.bst`
- [ ] `installer-stack.bst` does NOT include `installer/installer-sysupdate.bst`
- [ ] `bluefin-server-installer.bst` depends on `oci/bluefin-server-ddi.bst`
- [ ] DDI decompression step is AFTER the cpio step in `bluefin-server-installer.bst`
- [ ] `bluefin-server-ddi.bst` sizes filesystem at content + 10% (no hardcoded floor)
- [ ] Lab build template points at correct repo and installer element

## Related

- `projectbluefin/knuckle` — TUI installer source; `internal/install/ddi.go`
- `docs/skills/nspawn-machine-image.md` — tarball artifact pattern
- FSDK `elements/vm/minimal-secure/` — repart + ukify toolchain reference

