kind: script
description: |
  Produce the Bluefin Server DDI live installer disk image.

  Output: bluefin-server-installer-<ver>.raw.zst + SHA256SUMS

  The installer is a single-partition GPT disk image:
    - partition 1: ESP (vfat) — contains installer.efi (UKI)

  When booted, installer.efi starts a live systemd initrd that:
    1. Calls systemd-sysupdate to pull the OS DDI from GitHub Releases
       (transfer config baked into the installer via installer-sysupdate.bst)
    2. Runs systemd-repart --dry-run=no DEVICE using the bundled repart.d
       configs (installer-repart.bst), which write the DDI to the target disk
    3. Runs bootctl install + systemd-firstboot for initial provisioning
    4. Reboots into the installed OS

  No OS payload is embedded in the installer — it is pulled by sysupdate at
  install time. This keeps the installer small (~200MB UKI vs multi-GB media).

  ── REMAINING STUB ──────────────────────────────────────────────────────────
  TODO: UKI generation (one remaining blocker)
    The installer.efi UKI must be produced with:
      ukify build \
        --linux=$(ls /layer/usr/lib/modules/*/vmlinuz | head -1) \
        --initrd=installer.cpio.zst \
        --cmdline="systemd.unit=installer.target console=ttyS0,115200" \
        --output=/layer/boot/efi/EFI/Linux/installer.efi
    Requires:
      a) dracut run against installer-stack to generate installer.cpio.zst
         (dracut modules needed: systemd systemd-repart network base)
      b) Add freedesktop-sdk.bst:components/systemd-ukify.bst as build-dep
      c) Secure Boot signing decision: unsigned works for dev/USB installs;
         vendor-signed requires a Bluefin key pair injected at CI time.
    Until resolved the ESP step is stubbed. Replace the dd stub below with
    the systemd-repart + ukify assembly once dracut integration is confirmed.
  ────────────────────────────────────────────────────────────────────────────

build-depends:
  # Toolchain for assembly commands
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/zstd.bst
  # systemd-repart builds the GPT disk image from the staged rootfs + repart.d
  - freedesktop-sdk.bst:components/systemd.bst
  # The installer live-env rootfs (with sysupdate + repart configs), staged at /layer
  - filename: installer/installer-stack.bst
    config:
      location: /layer

variables:
  installer-version: "0.1.0"

config:
  commands:
    # ── Step 1: Create the installer ESP layout ──────────────────────────
    # TODO(UKI): Replace stub with ukify + dracut once initrd generation
    # is wired. The target path is fixed: /boot/efi/EFI/Linux/installer.efi
    - |
      set -eu
      mkdir -p /layer/boot/efi/EFI/Linux
      mkdir -p /layer/boot/efi/EFI/BOOT
      # ukify build \
      #   --linux="$(ls /layer/usr/lib/modules/*/vmlinuz | head -1)" \
      #   --initrd=/installer.cpio.zst \
      #   --cmdline="systemd.unit=installer.target console=ttyS0,115200" \
      #   --output=/layer/boot/efi/EFI/Linux/installer.efi

    # ── Step 2: Assemble installer GPT disk image via systemd-repart ─────
    # systemd-repart --empty=create builds a fresh GPT disk from scratch
    # using the repart.d configs staged under /layer/usr/lib/repart.d/.
    # When the real UKI exists the dd stub is replaced with this call:
    #   systemd-repart \
    #     --empty=create \
    #     --size=auto \
    #     --dry-run=no \
    #     --root=/layer \
    #     --definitions=/layer/usr/lib/repart.d \
    #     "%{install-root}/bluefin-server-installer-%{installer-version}.raw"
    - |
      set -eu
      OUT="%{install-root}"
      FNAME="bluefin-server-installer-%{installer-version}.raw"
      # Stub until UKI generation is wired — 1MB sparse placeholder.
      dd if=/dev/zero bs=1M count=1 of="${OUT}/${FNAME}" 2>/dev/null

    # ── Step 3: Compress + checksum for GitHub Releases / sysupdate ──────
    - |
      set -eu
      cd "%{install-root}"
      FNAME="bluefin-server-installer-%{installer-version}.raw"
      zstd --rm -T0 -19 "${FNAME}" -o "${FNAME}.zst"
      sha256sum --binary "${FNAME}.zst" > SHA256SUMS

