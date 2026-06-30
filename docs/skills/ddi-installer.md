# DDI Live Installer

## What this is

A DDI (Discoverable Disk Image) based live installer for Bluefin Server.
No bootc, no OCI image pull — purely systemd-native network-pull model:

1. Boot from the installer USB (a GPT disk image with one ESP partition)
2. The installer live env runs `systemd-sysupdate` to pull the OS DDI from
   GitHub Releases
3. `systemd-repart` applies the DDI to the target disk
4. `bootctl install` + `systemd-firstboot` provision the bootloader and
   initial configuration
5. Reboot into the installed OS

## Status

**Scaffolded — one remaining stub before it produces a real bootable image.**

- ✅ Element chain defined and graph resolves (`just validate-installer`)
- ✅ sysupdate.d transfer config wired (pulls OS DDI from GitHub Releases)
- ✅ repart.d target disk layout defined
- ✅ Release workflow wired (`.github/workflows/release-installer.yml`)
- 🔲 UKI generation (dracut initrd + ukify — see stub section below)

## Element chain

```
elements/
  installer/
    installer-stack.bst      kind: stack  — live installer env deps
    installer-repart.bst     kind: import — repart.d configs (target disk layout)
    installer-sysupdate.bst  kind: import — sysupdate.d transfer config
  oci/
    bluefin-server-installer.bst  kind: script — produces .raw.zst + SHA256SUMS
files/
  installer/
    repart.d/
      10-esp.conf             EFI System Partition (500M–1G, vfat)
      20-root-a.conf          Root slot A (CopyBlocks from sysupdate download)
      30-var.conf             /var (xfs, grows to fill disk)
    sysupdate.d/
      bluefin-server-ddi.conf sysupdate transfer config (url-file, GitHub Releases)
```

## Network-pull install flow

```
Installer boot
     │
     ▼
installer.efi (UKI: kernel + initrd)
     │
     ▼
systemd-sysupdate --definitions=/usr/lib/sysupdate.d update
     │  reads: files/installer/sysupdate.d/bluefin-server-ddi.conf
     │  fetches: bluefin-server-ddi-<ver>.raw.zst from GitHub Releases
     │  verifies: SHA256SUMS
     │  writes: /run/installer/bluefin-server-ddi-<ver>.raw
     │  symlinks: /run/installer/bluefin-server-ddi.raw → versioned file
     │
     ▼
systemd-repart --dry-run=no /dev/TARGET
     │  reads: /usr/lib/repart.d/ (10-esp, 20-root-a, 30-var)
     │  20-root-a.conf: CopyBlocks=/run/installer/bluefin-server-ddi.raw
     │  creates ESP, root-a partition (DDI copied), var partition
     │
     ▼
bootctl install --esp-path=/dev/TARGET-esp-partition
     │
     ▼
systemd-firstboot (hostname, locale, credentials)
     │
     ▼
reboot → installed Bluefin Server
```

## Installer live environment (`installer-stack.bst`)

NOT distroless — the installer needs tools and a shell.

| Component | Purpose |
|---|---|
| `systemd.bst` | repart + sysupdate + firstboot + bootctl |
| `cryptsetup.bst` | LUKS partition support |
| `dracut.bst` | initrd generation (see UKI stub) |
| `kernel-server.bst` | installer kernel |
| `installer-repart.bst` | repart.d staging → /usr/lib/repart.d/ |
| `installer-sysupdate.bst` | sysupdate.d staging → /usr/lib/sysupdate.d/ |

## sysupdate.d transfer config (`bluefin-server-ddi.conf`)

```ini
[Transfer]
ProtectVersion=%A

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

`CopyBlocks=/run/installer/bluefin-server-ddi.raw` in `20-root-a.conf` reads
the file that sysupdate deposits at the `CurrentSymlink` path.

## repart.d partition layout (TARGET disk)

| Config | Type | Format | Notes |
|---|---|---|---|
| `10-esp.conf` | esp | vfat | 500M–1G; bootloader + UKIs go here |
| `20-root-a.conf` | root | — | DDI applied via `CopyBlocks=` |
| `30-var.conf` | var | xfs | writable; grows to fill remaining space |

## Remaining stub: UKI generation

The `bluefin-server-installer.bst` script element is stubbed at the step
that produces `installer.efi`. Replace the `dd` stub with:

```bash
# Step A: generate the installer initrd via dracut
dracut \
  --kver "$(ls /layer/usr/lib/modules | head -1)" \
  --add "systemd systemd-repart network base" \
  --no-hostonly \
  installer.cpio.zst

# Step B: assemble the UKI
ukify build \
  --linux="$(ls /layer/usr/lib/modules/*/vmlinuz | head -1)" \
  --initrd=installer.cpio.zst \
  --cmdline="systemd.unit=installer.target console=ttyS0,115200" \
  --output=/layer/boot/efi/EFI/Linux/installer.efi
```

Required additions to `bluefin-server-installer.bst`:
- `freedesktop-sdk.bst:components/systemd-ukify.bst` as `build-depends`

**Secure Boot signing decision:**
- Dev/CI: unsigned UKI — `--secureboot-private-key` not passed, works for USB installs
- Release: sign with a Bluefin vendor key pair injected at CI time

## Release workflow

`.github/workflows/release-installer.yml` publishes on `installer-v*` tags:

```
git tag installer-v0.1.0
git push origin installer-v0.1.0
```

Uploads to GitHub Releases:
- `bluefin-server-installer-<ver>.raw.zst`
- `SHA256SUMS`

The OS DDI (`bluefin-server-ddi-<ver>.raw.zst`) is a separate release artifact
published by a future `elements/installer/os-snapshot.bst` element once the
server rootfs DDI packaging is defined (separate todo from UKI generation).

## Justfile commands

```
just validate-installer    # resolve element graph — works today
just build-installer       # build .raw.zst (stub until UKI wired)
just export-installer      # export artifacts to dist/
```

## Related

- `docs/skills/nspawn-machine-image.md` — the tarball artifact pattern that
  this release workflow mirrors
- `elements/oci/brew-nspawn.bst` — reference script element producing a
  non-OCI release artifact
- FSDK `elements/vm/minimal-secure/sysupdate-config.bst` — FSDK's own
  sysupdate.d wiring pattern

