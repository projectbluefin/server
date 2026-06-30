kind: script
description: |
  Produce the Bluefin Server DDI live installer disk image.

  Output: bluefin-server-installer-<ver>.raw + SHA256SUMS

  The .raw file is a GPT disk image with:
    - partition 1: ESP (vfat) — contains the installer UKI at /EFI/Linux/
    - partition 2: data — contains the OS DDI payload (erofs root image)

  When booted, the installer UKI starts a minimal systemd initrd that runs
  systemd-repart against the target disk using the repart.d configs in
  /usr/lib/repart.d/, which copy the OS DDI to the installed root slot.

  ── BLOCKERS ────────────────────────────────────────────────────────────────
  TODO(1): UKI generation
    The installer.efi UKI must be produced with:
      ukify build --linux=<vmlinuz> --initrd=<installer.cpio> \
        --cmdline="systemd.unit=installer.target console=ttyS0,115200"
    This requires:
      a) dracut run against the installer-stack to produce installer.cpio
      b) systemd-ukify available as a build-dep (freedesktop-sdk.bst:components/systemd-ukify.bst)
      c) A decision on Secure Boot signing: unsigned for dev, vendor-signed for release.
    Until (a)-(c) are resolved the ESP step below is stubbed out.

  TODO(2): OS DDI payload
    The erofs OS root image (bluefin-server-root.erofs) must be produced by:
      mkfs.erofs --all-root bluefin-server-root.erofs /layer
    where /layer is the staged bluefin-server OS rootfs (without bootc —
    os-stack.bst minus the ostree/composefs/bootc deps).
    A new element elements/installer/os-snapshot.bst will produce this.
    Blocked on: agreement on whether to strip bootc from the OS for DDI.
  ────────────────────────────────────────────────────────────────────────────

  Once TODO(1) and TODO(2) are resolved, replace the stub commands below with
  the real UKI + erofs assembly steps.

build-depends:
  # Toolchain for assembly commands
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/tar.bst
  - freedesktop-sdk.bst:components/zstd.bst
  # systemd-repart is the tool that assembles the GPT disk image
  - freedesktop-sdk.bst:components/systemd.bst
  # erofs-utils needed at build time to create the OS payload image
  - freedesktop-sdk.bst:components/erofs-utils.bst
  # The installer live-env rootfs, staged at /layer
  - filename: installer/installer-stack.bst
    config:
      location: /layer

variables:
  installer-version: "0.1.0"

config:
  commands:
    # ── Step 1: Create the installer ESP layout ──────────────────────────
    # TODO(1): Replace this stub with real UKI generation once dracut
    # integration and signing decision are resolved. For now, create the
    # minimum directory structure so systemd-repart can populate the ESP.
    - |
      set -eu
      mkdir -p /layer/boot/efi/EFI/Linux
      mkdir -p /layer/boot/efi/EFI/BOOT
      # Placeholder: ukify will write installer.efi here
      # ukify build \
      #   --linux=/layer/usr/lib/modules/*/vmlinuz \
      #   --initrd=/installer.cpio.zst \
      #   --cmdline="systemd.unit=installer.target console=ttyS0,115200" \
      #   --output=/layer/boot/efi/EFI/Linux/installer.efi

    # ── Step 2: Produce the installer disk image ─────────────────────────
    # TODO(2): Add the OS DDI erofs image as partition 2 (data partition).
    # The final command will be:
    #   systemd-repart \
    #     --empty=create \
    #     --size=auto \
    #     --dry-run=no \
    #     --root=/layer \
    #     --definitions=/usr/lib/repart.d \
    #     "%{install-root}/bluefin-server-installer-%{installer-version}.raw"
    #
    # For now, produce a stub disk image so the element chain can be
    # validated without building the full OS DDI.
    - |
      set -eu
      OUT="%{install-root}"
      FNAME="bluefin-server-installer-%{installer-version}.raw"
      # Stub: 1MB sparse file so `bst show` + validate works without a build.
      # Replace with the systemd-repart call above once blockers are resolved.
      dd if=/dev/zero bs=1M count=1 of="${OUT}/${FNAME}" 2>/dev/null
      echo "NOTE: stub disk image — replace with systemd-repart assembly" \
           > "${OUT}/INSTALLER_BUILD_STUB.txt"

    # ── Step 3: Checksums for systemd-sysupdate ──────────────────────────
    - |
      set -eu
      cd "%{install-root}"
      sha256sum --binary "bluefin-server-installer-%{installer-version}.raw" \
        > SHA256SUMS
