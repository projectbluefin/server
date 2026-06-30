# DDI Live Installer

## What this is

A DDI (Discoverable Disk Image) based live installer for Bluefin Server.
When booted, it runs `systemd-repart` to partition a target disk and copy
the OS DDI payload to it. No bootc, no OCI pull — purely systemd-native.

## Status

**Scaffolded — two blockers before it builds.** See TODOs below.

## Design

### Element chain

```
elements/
  installer/
    installer-stack.bst       kind: stack  — live installer env deps
    installer-repart.bst      kind: import — repart.d configs (target disk layout)
  oci/
    bluefin-server-installer.bst  kind: script — produces .raw + SHA256SUMS
files/
  installer/
    repart.d/
      10-esp.conf             EFI System Partition (500M–1G, vfat)
      20-root-a.conf          Root slot A (erofs DDI payload via CopyBlocks=auto)
      30-var.conf             /var (xfs, grows to fill disk)
```

### Installer live environment (`installer-stack.bst`)

The live installer is NOT distroless — it keeps bash and tooling.
Key components:
- `freedesktop-sdk.bst:components/systemd.bst` — full systemd includes
  `systemd-repart`, `systemd-firstboot`, and `bootctl`
- `freedesktop-sdk.bst:components/cryptsetup.bst` — LUKS partition support
- `freedesktop-sdk.bst:components/erofs-utils.bst` — erofs DDI creation
- `freedesktop-sdk.bst:components/dracut.bst` — initrd generation
- `bluefin-server/kernel-server.bst` — the installer kernel

### Disk image output (`bluefin-server-installer.bst`)

The final artifact is a GPT disk image produced by `systemd-repart --empty=create`.
It contains:
1. ESP (vfat) — installer UKI at `/EFI/Linux/installer.efi`
2. Data partition — OS DDI erofs image (`bluefin-server-root.erofs`)

When booted, the installer UKI starts a systemd initrd that:
1. Finds the target disk (via kernel cmdline or interactive prompt)
2. Runs `systemd-repart --dry-run=no TARGET_DISK` with the bundled `repart.d`
3. Calls `bootctl install` to install systemd-boot into the new ESP
4. Runs `systemd-firstboot` for hostname/locale/credentials
5. Reboots into the installed OS

### repart.d partition layout (TARGET disk)

| Config | Type | Format | Notes |
|---|---|---|---|
| `10-esp.conf` | esp | vfat | 500M–1G; bootloader lives here |
| `20-root-a.conf` | root | erofs | DDI payload copied via `CopyBlocks=auto` |
| `30-var.conf` | var | xfs | writable; grows to fill remaining space |

`CopyBlocks=auto` in `20-root-a.conf` tells systemd-repart to find the
matching DDI source from `/run/repart-sources/` — the initrd populates
this dir by loopback-mounting the OS DDI partition from the installer media.

## Blockers

### Blocker 1: UKI generation

The installer needs a UKI (`installer.efi`) containing:
- kernel: from `bluefin-server/kernel-server.bst`
- initrd: built by dracut against `installer-stack.bst`
- cmdline: `systemd.unit=installer.target console=ttyS0,115200`

Build command (once inputs exist):
```
ukify build \
  --linux=$(ls /layer/usr/lib/modules/*/vmlinuz | head -1) \
  --initrd=installer.cpio.zst \
  --cmdline="systemd.unit=installer.target console=ttyS0,115200" \
  --output=/layer/boot/efi/EFI/Linux/installer.efi
```

**Decision needed:** Secure Boot signing for the installer UKI?
- Dev/CI: unsigned (acceptable — installer is not the installed OS)
- Release: sign with `freedesktop-sdk.bst:components/systemd-ukify.bst` +
  a Bluefin vendor key pair (store separately, inject at CI time)

Add `freedesktop-sdk.bst:components/systemd-ukify.bst` as a `build-depends`
in `bluefin-server-installer.bst` once this is resolved.

### Blocker 2: OS DDI payload format

The `20-root-a.conf` repart config uses `CopyBlocks=auto`. This requires a
source DDI image that `systemd-repart` can find at install time.

**Options:**

**A. erofs image in a data partition of the installer media** (recommended)
  - Build `elements/installer/os-snapshot.bst` (kind: script):
    ```
    mkfs.erofs --all-root bluefin-server-root.erofs /layer
    ```
    where `/layer` is a non-bootc OS stack (new element needed)
  - The installer disk gets a second partition containing this erofs image
  - The installer initrd loopback-mounts it and exposes it via
    `/run/repart-sources/`
  - **Sub-blocker**: the OS stack for DDI must drop ostree/composefs/bootc
    deps from `bluefin-server/os-stack.bst`. Needs a separate stack element,
    e.g. `elements/installer/server-rootfs-stack.bst`.

**B. Network pull via systemd-sysupdate** (simpler installer, larger attack surface)
  - No data partition needed
  - Installer initrd runs `systemd-sysupdate` to pull the OS DDI from
    GitHub Releases
  - Requires network during installation
  - The sysupdate transfer config would be baked into the installer

**Decision needed:** Option A (offline, bigger installer) or B (network required)?

## Justfile commands

```
just validate-installer    # resolve element graph — works today
just build-installer       # build stub .raw (stub until blockers resolved)
just export-installer      # export .raw + SHA256SUMS to dist/
```

## Element references

All FSDK element references use the junction override in
`elements/freedesktop-sdk.bst`, which redirects:
- `components/systemd.bst` → `gnome-build-meta.bst:core-deps/systemd.bst`
- `components/systemd-ukify.bst` → `gnome-build-meta.bst:core-deps/systemd-ukify.bst`

This is inherited automatically — no special handling needed in installer
elements.

## Related

- `docs/skills/nspawn-machine-image.md` — the tarball artifact pattern
  (brew-nspawn.bst) that `bluefin-server-installer.bst` is modeled after
- `elements/oci/brew-nspawn.bst` — reference script element producing
  a non-OCI release artifact
- FSDK `elements/vm/minimal-secure/` — FSDK's own secure-boot VM image
  that uses the same repart + ukify toolchain
