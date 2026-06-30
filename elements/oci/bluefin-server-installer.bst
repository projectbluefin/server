kind: script
description: |
  Produce the Bluefin Server DDI live installer disk image.

  Output: bluefin-server-installer-<ver>.raw.zst + SHA256SUMS

  Initrd approach: dracut-free, cpio-native.
  The installer-stack rootfs is packed directly into a cpio.zst initrd using
  POSIX find + cpio. No initrd generator is needed — systemd PID 1 works
  correctly when the initrd is a plain rootfs cpio with /init -> systemd.
  This is the approach the systemd project uses for its own test images.

  Build pipeline:
    1. Add /init symlink and bluefin-install script to the staged rootfs
    2. Link default.target -> installer.target
    3. Pack rootfs as newc cpio + zstd -> installer.cpio.zst
    4. ukify build: kernel + cpio.zst -> installer.efi (unsigned UKI)
    5. systemd-repart --empty=create: assemble single-partition GPT disk
       (ESP only; the installer pulls the OS DDI over the network at runtime)
    6. Compress final disk as .raw.zst + SHA256SUMS for GitHub Releases

build-depends:
  # Toolchain for assembly
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/cpio.bst      # newc cpio archive creation
  - freedesktop-sdk.bst:components/findutils.bst  # find for cpio pipe
  - freedesktop-sdk.bst:components/zstd.bst       # compress initrd + final disk
  # ukify assembles the UKI (kernel + initrd + cmdline -> .efi)
  - freedesktop-sdk.bst:components/systemd-ukify.bst
  # systemd-repart assembles the GPT installer disk image
  - freedesktop-sdk.bst:components/systemd.bst
  # Installer live-env rootfs staged at /layer
  - filename: installer/installer-stack.bst
    config:
      location: /layer

variables:
  installer-version: "0.1.0"

config:
  commands:
    # ── Step 1: Prepare the initrd rootfs ───────────────────────────────
    # /init is required by the Linux initrd protocol (kernel hands control
    # to /init as PID 1). For systemd-native initrds this is a symlink.
    - |
      set -eu
      # systemd-native initrd: /init -> PID 1
      ln -sf usr/lib/systemd/systemd /layer/init
      # Mount points needed by the installer service
      mkdir -p /layer/efi /layer/mnt/esp /layer/mnt/root /layer/run/installer

    # ── Step 2: Write the bluefin-install orchestration script ──────────
    # Written inline to avoid a separate import element just for one script.
    - |
      set -eu
      mkdir -p /layer/usr/bin
      cat > /layer/usr/bin/bluefin-install << 'SCRIPT'
      #!/bin/bash
      set -euo pipefail
      log()  { echo "[bluefin-install] $*"; }
      fail() { log "ERROR: $*"; exit 1; }

      log "Bluefin Server DDI Installer starting"

      # 1. Pull the OS DDI from GitHub Releases
      log "Pulling OS DDI via systemd-sysupdate..."
      systemd-sysupdate --definitions=/usr/lib/sysupdate.d update \
        || fail "sysupdate failed — check network connectivity and release URL"

      [ -e /run/installer/bluefin-server-ddi.raw ] \
        || fail "/run/installer/bluefin-server-ddi.raw missing after sysupdate"
      log "DDI ready: $(ls -lh /run/installer/bluefin-server-ddi.raw)"

      # 2. Detect target disk
      # Override with installer.disk=<path> on the kernel cmdline if needed.
      DISK=""
      for arg in $(cat /proc/cmdline); do
        case "$arg" in installer.disk=*) DISK="${arg#installer.disk=}" ;; esac
      done
      if [ -z "$DISK" ]; then
        for candidate in /dev/vda /dev/sda /dev/nvme0n1 /dev/mmcblk0; do
          [ -b "$candidate" ] || continue
          RO=$(cat "/sys/block/$(basename "$candidate")/ro" 2>/dev/null || echo 1)
          [ "$RO" = "0" ] && DISK="$candidate" && break
        done
      fi
      [ -n "$DISK" ] \
        || fail "No writable disk found. Pass installer.disk=/dev/DEVICE on cmdline."
      log "Target disk: $DISK"

      # 3. Partition and install OS via systemd-repart
      # Reads /usr/lib/repart.d/:
      #   10-esp.conf    -> creates vfat ESP (empty; bootloader installed below)
      #   20-root-a.conf -> creates root partition, copies DDI via CopyBlocks=
      #   30-var.conf    -> creates /var xfs partition
      log "Running systemd-repart..."
      systemd-repart \
        --dry-run=no \
        --empty=force \
        --definitions=/usr/lib/repart.d \
        "$DISK" \
        || fail "systemd-repart failed"

      # 4. Install the bootloader into the newly created ESP
      # Mount ESP and root-a, run bootctl install, then unmount.
      ESP_DEV=$(lsblk -rno PATH,PARTTYPE "$DISK" 2>/dev/null \
        | awk '$2 == "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" {print $1}' | head -1)
      ROOT_DEV=$(lsblk -rno PATH,PARTLABEL "$DISK" 2>/dev/null \
        | awk '$2 == "bluefin-server-root-a" {print $1}' | head -1)

      if [ -n "$ESP_DEV" ] && [ -n "$ROOT_DEV" ]; then
        mount "$ESP_DEV"  /mnt/esp
        mount -o ro "$ROOT_DEV" /mnt/root
        bootctl install --esp-path=/mnt/esp --root=/mnt/root \
          || log "WARNING: bootctl install failed (non-fatal)"
        umount /mnt/esp /mnt/root
      else
        log "WARNING: Could not locate ESP ($ESP_DEV) or root ($ROOT_DEV)."
        log "  Bootloader not installed — run bootctl manually after reboot."
      fi

      log "Installation complete. Powering off."
      sleep 2
      SCRIPT
      chmod +x /layer/usr/bin/bluefin-install

    # ── Step 3: Wire default.target -> installer.target ─────────────────
    - |
      set -eu
      rm -f /layer/usr/lib/systemd/system/default.target
      ln -sf installer.target \
        /layer/usr/lib/systemd/system/default.target
      # Enable installer.service for the installer.target wants
      mkdir -p /layer/usr/lib/systemd/system/installer.target.wants
      ln -sf /usr/lib/systemd/system/installer.service \
        /layer/usr/lib/systemd/system/installer.target.wants/installer.service

    # ── Step 4: Pack initrd cpio ─────────────────────────────────────────
    # find . from /layer gives paths like ./usr/bin/... which is exactly
    # the newc format the kernel expects. The kernel strips the leading dot.
    - |
      set -eu
      ( cd /layer && find . -print0 \
          | cpio --null --create --format=newc ) \
        | zstd -T0 -19 -q -o /installer.cpio.zst
      ls -lh /installer.cpio.zst

    # ── Step 5: Build the UKI ────────────────────────────────────────────
    # Unsigned UKI — acceptable for USB installer media. Secure Boot
    # signing can be layered on by passing --secureboot-private-key /
    # --secureboot-certificate if keys are injected at CI time.
    - |
      set -eu
      KVER=$(ls /layer/usr/lib/modules | head -1)
      mkdir -p /layer/boot/efi/EFI/Linux
      ukify build \
        --linux="/layer/usr/lib/modules/${KVER}/vmlinuz" \
        --initrd=/installer.cpio.zst \
        --cmdline="systemd.unit=installer.target console=ttyS0,115200 rw" \
        --output=/layer/boot/efi/EFI/Linux/installer.efi
      ls -lh /layer/boot/efi/EFI/Linux/installer.efi

    # ── Step 6: Assemble installer GPT disk image ────────────────────────
    # installer-stack/repart.d has only 10-esp.conf so the installer media
    # is a minimal single-partition GPT with just the ESP (+ UKI inside).
    # The OS DDI is not embedded — it is pulled at install time by sysupdate.
    #
    # Note: we use a dedicated repart.d just for the INSTALLER DISK (1 conf:
    # 10-esp.conf) which is different from the TARGET DISK repart.d (3 confs
    # staged in /usr/lib/repart.d/ inside the installer rootfs).
    - |
      set -eu
      OUT="%{install-root}"
      FNAME="bluefin-server-installer-%{installer-version}.raw"
      mkdir -p /installer-media-repart.d
      cat > /installer-media-repart.d/10-esp.conf << 'RCONF'
      [Partition]
      Type=esp
      Format=vfat
      CopyFiles=/boot/efi:/
      SizeMinBytes=500M
      SizeMaxBytes=1G
      RCONF
      systemd-repart \
        --empty=create \
        --size=auto \
        --dry-run=no \
        --root=/layer \
        --definitions=/installer-media-repart.d \
        "${OUT}/${FNAME}"
      ls -lh "${OUT}/${FNAME}"

    # ── Step 7: Compress + checksum ──────────────────────────────────────
    - |
      set -eu
      cd "%{install-root}"
      FNAME="bluefin-server-installer-%{installer-version}.raw"
      zstd --rm -T0 -19 -q "${FNAME}" -o "${FNAME}.zst"
      sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      ls -lh


