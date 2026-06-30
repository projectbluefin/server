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
  - freedesktop-sdk.bst:components/dosfstools.bst
  - freedesktop-sdk.bst:components/mtools.bst
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
      # Keep the network service users available even if sysusers runs too late.
      printf 'systemd-network:x:998:998:systemd Network Management:/run/systemd:/usr/sbin/nologin\nsystemd-resolve:x:997:997:systemd Resolver:/run/systemd:/usr/sbin/nologin\n' >> /layer/etc/passwd
      printf 'systemd-network:x:998:\nsystemd-resolve:x:997:\n' >> /layer/etc/group
      # Ensure systemd-sysusers runs early (materialises systemd-network user),
      # and networkd/resolved are enabled so the installer can reach GitHub.
      mkdir -p /layer/usr/lib/systemd/system/sysinit.target.wants
      ln -sf /usr/lib/systemd/system/systemd-sysusers.service \
        /layer/usr/lib/systemd/system/sysinit.target.wants/systemd-sysusers.service
      ln -sf /usr/lib/systemd/system/systemd-networkd.service \
        /layer/usr/lib/systemd/system/sysinit.target.wants/systemd-networkd.service
      ln -sf /usr/lib/systemd/system/systemd-resolved.service \
        /layer/usr/lib/systemd/system/sysinit.target.wants/systemd-resolved.service
      # DHCP on all ethernet interfaces — needed for sysupdate to reach GitHub.
      mkdir -p /layer/usr/lib/systemd/network
      printf '[Match]\nName=en* eth* ens* enp*\n\n[Network]\nDHCP=yes\n' \
        > /layer/usr/lib/systemd/network/80-dhcp.network

    # ── Step 2: Write the bluefin-install orchestration script ──────────
    # Written inline to avoid a separate import element just for one script.
    - |
      set -eu
      mkdir -p /layer/usr/bin
      cat > /layer/usr/bin/bluefin-install << 'SCRIPT'
      #!/bin/bash
      set -euo pipefail
      exec >/dev/console 2>&1
      log()  { echo "[bluefin-install] $*"; }
      fail() { log "ERROR: $*"; exit 1; }

      log "Bluefin Server DDI Installer starting"

      # 1. Detect target disk.
      # Override with installer.disk=<path> on the kernel cmdline if needed.
      DISK=""
      for arg in $(cat /proc/cmdline); do
        case "$arg" in installer.disk=*) DISK="${arg#installer.disk=}" ;; esac
      done
      if [ -z "$DISK" ]; then
        # vdb is the second virtio disk (target) when vda is the read-only installer media.
        for candidate in /dev/vda /dev/vdb /dev/sda /dev/sdb /dev/nvme0n1 /dev/mmcblk0; do
          [ -b "$candidate" ] || continue
          RO=$(cat "/sys/block/$(basename "$candidate")/ro" 2>/dev/null || echo 1)
          [ "$RO" = "0" ] && DISK="$candidate" && break
        done
      fi
      [ -n "$DISK" ] \
        || fail "No writable disk found. Pass installer.disk=/dev/DEVICE on cmdline."
      log "Target disk: $DISK"

      # 2. Detect a local DDI source device (for VM dev/test — avoids network download).
      # The DDI ext4 image is stamped with label 'bluefin-roota' by mkfs.ext4.
      # blkid -L is exact and immune to size/ordering assumptions.
      # If none is found, sysupdate downloads the DDI from GitHub Releases (production).
      DDI_SRC=""
      DDI_SRC=$(blkid -L bluefin-roota 2>/dev/null || true)

      # 3. Partition the target disk via systemd-repart.
      # If a local DDI source was found, point CopyBlocks at it directly so repart
      # streams block-for-block without buffering in RAM (prevents OOM on small VMs).
      # Otherwise keep the default definitions that use CopyBlocks from the sysupdate
      # download path (/run/installer/bluefin-server-ddi.raw).
      REPART_DEFS=/usr/lib/repart.d
      if [ -n "$DDI_SRC" ]; then
        log "Local DDI source detected: $DDI_SRC — skipping network download"
        mkdir -p /tmp/repart.d
        for f in /usr/lib/repart.d/*.conf; do
          base=$(basename "$f")
          out="/tmp/repart.d/$base"
          if [ "$base" = "20-root-a.conf" ]; then
            printf '%s\n' \
              '# Root partition — slot A' \
              '# systemd-repart copies the DDI payload block-for-block from the file that' \
              '# systemd-sysupdate downloaded to /run/installer/bluefin-server-ddi.raw' \
              '# (a stable CurrentSymlink set by the sysupdate transfer config).' \
              '# The source is a raw filesystem image; repart copies it verbatim.' \
              '[Partition]' \
              'Type=root' \
              'Label=bluefin-server-root-a' \
              "CopyBlocks=$DDI_SRC" \
              'SizeMinBytes=4G' \
              'SizeMaxBytes=16G' \
              > "$out"
          else
            cp "$f" "$out"
          fi
        done
        REPART_DEFS=/tmp/repart.d
      else
        log "No local DDI device found — pulling OS DDI via systemd-sysupdate..."
        systemctl start systemd-networkd-wait-online.service \
          || fail "network never became ready"
        /usr/lib/systemd/systemd-sysupdate --definitions=/usr/lib/sysupdate.d update \
          || fail "sysupdate failed — check network connectivity and release URL"
        [ -e /run/installer/bluefin-server-ddi.raw ] \
          || fail "/run/installer/bluefin-server-ddi.raw missing after sysupdate"
        log "DDI ready: $(ls -lh /run/installer/bluefin-server-ddi.raw)"
      fi

      log "Running systemd-repart (definitions: $REPART_DEFS)..."
      systemd-repart \
        --dry-run=no \
        --empty=force \
        --definitions="$REPART_DEFS" \
        "$DISK" \
        || fail "systemd-repart failed"

      # 4. Install the bootloader into the newly created ESP.
      ESP_DEV=""
      while read -r path type; do
        if [ "$type" = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" ]; then
          ESP_DEV="$path"
          break
        fi
      done < <(lsblk -rno PATH,PARTTYPE "$DISK" 2>/dev/null)

      ROOT_DEV=""
      while read -r path label; do
        if [ "$label" = "bluefin-server-root-a" ]; then
          ROOT_DEV="$path"
          break
        fi
      done < <(lsblk -rno PATH,PARTLABEL "$DISK" 2>/dev/null)

      if [ -n "$ESP_DEV" ] && [ -n "$ROOT_DEV" ]; then
        mount "$ESP_DEV"  /mnt/esp
        mount -o ro "$ROOT_DEV" /mnt/root
        # Install systemd-boot loader binaries.
        bootctl install --esp-path=/mnt/esp --root=/mnt/root \
          || log "WARNING: bootctl install failed (non-fatal)"
        # Create a loader entry pointing at the installed kernel.
        # systemd-boot uses Type 1 entries; kernel must be on the ESP.
        if [ -n "$KVER" ] && [ -f "/mnt/root/boot/vmlinuz" ]; then
          mkdir -p /mnt/esp/EFI/Linux /mnt/esp/loader/entries
          cp "/mnt/root/boot/vmlinuz" "/mnt/esp/vmlinuz-$KVER"
          printf 'title   Bluefin Server\nlinux   /vmlinuz-%s\noptions root=PARTLABEL=bluefin-server-root-a console=ttyS0,115200 rw\n' \
            "$KVER" > "/mnt/esp/loader/entries/bluefin-server.conf"
          log "Boot entry written for kernel $KVER"
        else
          log "WARNING: kernel not found under /mnt/root — manual boot entry required"
        fi
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

      # Clean up bloat from /layer before packing (reduces initrd size from 1.4G to ~100M!)
      rm -rf /layer/usr/lib/debug /layer/usr/share/doc /layer/usr/share/man /layer/usr/include
      find /layer -type f -name '*.debug' -delete

      # Strip unneeded large kernel modules (GPU, wireless, sound, media, bluetooth)
      KVER=$(ls /layer/usr/lib/modules | head -1)
      if [ -n "${KVER}" ]; then
        MOD_DIR="/layer/usr/lib/modules/${KVER}/kernel"
        if [ -d "${MOD_DIR}" ]; then
          rm -rf "${MOD_DIR}/drivers/gpu"
          rm -rf "${MOD_DIR}/drivers/net/wireless"
          rm -rf "${MOD_DIR}/drivers/sound" "${MOD_DIR}/sound"
          rm -rf "${MOD_DIR}/drivers/media"
          rm -rf "${MOD_DIR}/drivers/bluetooth"
          rm -rf "${MOD_DIR}/drivers/infiniband"
        fi
        # Re-run depmod to update module dependencies after stripping unneeded modules
        depmod -b /layer "${KVER}" || true
      fi

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
        --linux="/layer/boot/vmlinuz" \
        --initrd=/installer.cpio.zst \
        --cmdline="systemd.unit=installer.target console=ttyS0,115200 rw" \
        --output=/layer/boot/efi/EFI/Linux/installer.efi
      mkdir -p /layer/boot/efi/EFI/BOOT
      cp /layer/boot/efi/EFI/Linux/installer.efi /layer/boot/efi/EFI/BOOT/BOOTX64.EFI
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
      SizeMinBytes=1G
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
