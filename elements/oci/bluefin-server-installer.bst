kind: script
description: |
  Produce the Bluefin Server DDI live installer disk image.

  Output: bluefin-server-installer-<ver>.raw.zst + SHA256SUMS

  Initrd approach: dracut-free, cpio-native.
  The installer-stack rootfs is packed directly into a cpio.zst initrd using
  POSIX find + cpio. No initrd generator is needed — systemd PID 1 works
  correctly when the initrd is a plain rootfs cpio with /init -> systemd.
  This is the approach the systemd project uses for its own test images.

  The installer UI is knuckle (/opt/knuckle --os bluefin-ddi), a Go TUI
  (Bubble Tea) that presents a full interactive installer. It prompts for
  disk, username, password, and SSH key — then runs systemd-repart,
  provisions the user, and installs the bootloader.

  Build pipeline:
    1. Add /init symlink + mount points; wire networking and sysusers
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
  installer-version: "25.08.13"

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

    # ── Step 2: Wire default.target -> installer.target ─────────────────
    - |
      set -eu
      rm -f /layer/usr/lib/systemd/system/default.target
      ln -sf installer.target \
        /layer/usr/lib/systemd/system/default.target
      # Enable installer.service for the installer.target wants
      mkdir -p /layer/usr/lib/systemd/system/installer.target.wants
      ln -sf /usr/lib/systemd/system/installer.service \
        /layer/usr/lib/systemd/system/installer.target.wants/installer.service

    # ── Step 3: Pack initrd cpio ─────────────────────────────────────────
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
