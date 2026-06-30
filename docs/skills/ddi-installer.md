# DDI Live Installer

## What this is

A DDI (Discoverable Disk Image) based live installer for Bluefin Server.
No bootc, no OCI image pull, no dracut — purely systemd-native:

1. Boot from the installer USB (a GPT disk image with one ESP partition)
2. The installer live env runs `systemd-sysupdate` to pull the OS DDI from
   GitHub Releases
3. `systemd-repart` partitions the target disk and copies the DDI
4. `bootctl install` puts systemd-boot + the OS UKI into the new ESP
5. Power off → reboot into the installed OS

## Status

**Fully wired — no remaining stubs.** `just validate-installer` passes.

- ✅ Dracut-free cpio initrd assembled inline by the BST script element
- ✅ UKI built with `ukify` (unsigned; Secure Boot signing is opt-in)
- ✅ sysupdate.d transfer config pulls OS DDI from GitHub Releases
- ✅ repart.d target disk layout defined
- ✅ `bluefin-install` orchestration script (sysupdate → repart → bootctl)
- ✅ Release workflow (`.github/workflows/release-installer.yml`)
- 🔲 OS DDI artifact (`bluefin-server-ddi-@v.raw.zst`) — separate todo

## Element chain

```
elements/
  installer/
    installer-stack.bst      kind: stack  — live installer env deps (no dracut)
    installer-repart.bst     kind: import — repart.d configs (target disk layout)
    installer-sysupdate.bst  kind: import — sysupdate.d transfer config
    installer-units.bst      kind: import — installer.target + installer.service
  oci/
    bluefin-server-installer.bst  kind: script — cpio + ukify + repart → .raw.zst
files/
  installer/
    repart.d/
      10-esp.conf             ESP on TARGET disk (empty; bootctl populates it)
      20-root-a.conf          Root slot A (CopyBlocks from sysupdate download)
      30-var.conf             /var (xfs, grows to fill disk)
    sysupdate.d/
      bluefin-server-ddi.conf sysupdate transfer config (url-file, GitHub Releases)
    units/
      installer.target        Systemd target (waits for network + installer.service)
      installer.service       Oneshot: runs bluefin-install, poweroff on success
```

## Why no dracut

Dracut solves the problem of generating a minimal initrd from a running host by
introspecting hardware and adding only the needed modules. For a BST-built
installer image we already know exactly what's in the rootfs — the
`installer-stack.bst` is the complete, reproducible live environment.

Packing the entire rootfs as a cpio with `find . | cpio --null --create
--format=newc` and pointing `ukify` at it is the approach the systemd project
uses for its own test images (`mkosi`-built images use the same mechanism
without a generator). It requires only `cpio` + `find` + `zstd` — all in FSDK
`components/`.

The initrd is larger than a hand-tuned dracut output (because it includes all
kernel modules), but size is not a concern for USB installer media, and the
approach is simpler to maintain and debug.

## Initrd assembly (cpio-native)

The `bluefin-server-installer.bst` script element:

```bash
# 1. Add /init symlink (Linux initrd protocol: kernel executes /init as PID 1)
ln -sf usr/lib/systemd/systemd /layer/init

# 2. Link default.target -> installer.target
ln -sf installer.target /layer/usr/lib/systemd/system/default.target

# 3. Pack the entire rootfs as a newc cpio archive + zstd-compress
( cd /layer && find . -print0 | cpio --null --create --format=newc ) \
  | zstd -T0 -19 -q -o /installer.cpio.zst

# 4. Build the UKI (unsigned for dev; add --secureboot-* for release signing)
KVER=$(ls /layer/usr/lib/modules | head -1)
ukify build \
  --linux="/layer/usr/lib/modules/${KVER}/vmlinuz" \
  --initrd=/installer.cpio.zst \
  --cmdline="systemd.unit=installer.target console=ttyS0,115200 rw" \
  --output=/layer/boot/efi/EFI/Linux/installer.efi

# 5. Assemble a single-partition GPT disk (ESP only) for the installer media
#    (separate from the target-disk repart.d in /usr/lib/repart.d/)
systemd-repart --empty=create --size=auto --dry-run=no \
  --root=/layer --definitions=/installer-media-repart.d \
  bluefin-server-installer-<ver>.raw
```

## Network-pull install flow

```
Installer boot (UEFI reads ESP → systemd-boot → installer.efi)
     │
     ▼
installer.efi (UKI: kernel + cpio initrd)
     │
     ▼
systemd PID 1 starts, reaches installer.target
     │
     ▼
installer.service → bluefin-install script:
     │
     ├─ systemd-sysupdate --definitions=/usr/lib/sysupdate.d update
     │      fetches bluefin-server-ddi-@v.raw.zst from GitHub Releases
     │      deposits /run/installer/bluefin-server-ddi.raw
     │
     ├─ systemd-repart --dry-run=no --empty=force /dev/TARGET
     │      reads /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     │      20-root-a: CopyBlocks=/run/installer/bluefin-server-ddi.raw
     │
     ├─ bootctl install --esp-path=/mnt/esp --root=/mnt/root
     │      installs systemd-boot + OS UKI into the new ESP
     │
     └─ systemctl poweroff
          │
          ▼
     Reboot into installed Bluefin Server
```

## Target disk detection

The `bluefin-install` script auto-detects the first writable non-removable
block device (`/dev/vda`, `/dev/sda`, `/dev/nvme0n1`, `/dev/mmcblk0`).
To override, pass `installer.disk=/dev/TARGET` on the kernel cmdline.

## Secure Boot signing (opt-in)

The installer UKI is produced unsigned by default. To produce a signed UKI:

```bash
# Add to ukify build invocation in bluefin-server-installer.bst:
--secureboot-private-key=/path/to/vendor.key \
--secureboot-certificate=/path/to/vendor.crt
```

Inject the key files as BST secrets or CI secrets. The FSDK pattern for this
is in `elements/vm/minimal-secure/signed-boot.bst` (uses `kind: local` sources
for the key files — keep those out of the repo).

## sysupdate.d transfer config

```ini
[Source]
Type=url-file
Path=https://github.com/castrojo/bluefin-server/releases/download/
MatchPattern=bluefin-server-ddi-@v.raw.zst
SHA256Sum=SHA256SUMS

[Target]
Type=regular-file
Path=/run/installer/
MatchPattern=bluefin-server-ddi-@v.raw
CurrentSymlink=/run/installer/bluefin-server-ddi.raw
```

## OS DDI artifact (open item)

`bluefin-server-ddi-@v.raw.zst` is the erofs partition image that sysupdate
pulls. It does NOT exist yet. Building it requires:

1. A non-bootc server rootfs stack (strip ostree/composefs/bootc from
   `bluefin-server/os-stack.bst` → new `elements/installer/server-rootfs-stack.bst`)
2. An erofs image element:
   ```bash
   mkfs.erofs --all-root bluefin-server-ddi.raw /layer
   zstd --rm -T0 -19 bluefin-server-ddi.raw -o bluefin-server-ddi-<ver>.raw.zst
   ```
3. A corresponding `elements/oci/bluefin-server-ddi.bst` script element
4. Adding the DDI artifact to `release-installer.yml`

## Justfile commands

```
just validate-installer    # resolve element graph — works today
just build-installer       # full build: cpio + ukify + systemd-repart
just export-installer      # export .raw.zst + SHA256SUMS to dist/
```

## Release

`.github/workflows/release-installer.yml` publishes on `installer-v*` tags:
```
git tag installer-v0.1.0 && git push origin installer-v0.1.0
```
Uploads `bluefin-server-installer-<ver>.raw.zst` + `SHA256SUMS`.

## Related

- `docs/skills/nspawn-machine-image.md` — tarball artifact pattern
- `elements/oci/brew-nspawn.bst` — reference for non-OCI script elements
- FSDK `elements/vm/minimal-secure/` — repart + ukify toolchain reference


