kind: script
description: |
  Produce the Bluefin Server DDI live installer disk image.

  Output: bluefin-server-installer-<ver>.raw.zst + SHA256SUMS

  Offline installer: the OS DDI payload is embedded as a data partition on
  the installer media. No network required at install time.

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
    1. Add /init symlink + mount points
    2. Link default.target -> installer.target
    3. Pack rootfs as newc cpio + zstd -> installer.cpio.zst
    4. ukify build: kernel + cpio.zst -> installer.efi (unsigned UKI)
    5. Decompress DDI payload into /layer for embedding (after cpio, not in initrd)
    6. systemd-repart --empty=create: assemble two-partition GPT disk
       (ESP with UKI + data partition with embedded DDI payload)
    7. Compress final disk as .raw.zst + SHA256SUMS for GitHub Releases

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
  # OS DDI payload staged at /ddi — embedded into the installer media data partition
  - filename: oci/bluefin-server-ddi.bst
    config:
      location: /ddi

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
      # System users for networkd/resolved
      printf 'systemd-network:x:998:998:systemd Network Management:/run/systemd:/usr/sbin/nologin\nsystemd-resolve:x:997:997:systemd Resolver:/run/systemd:/usr/sbin/nologin\n' >> /layer/etc/passwd
      printf 'systemd-network:x:998:\nsystemd-resolve:x:997:\n' >> /layer/etc/group
      # Enable sysusers, networkd, resolved, sshd at boot
      mkdir -p /layer/usr/lib/systemd/system/sysinit.target.wants
      ln -sf /usr/lib/systemd/system/systemd-sysusers.service \
        /layer/usr/lib/systemd/system/sysinit.target.wants/systemd-sysusers.service
      mkdir -p /layer/usr/lib/systemd/system/multi-user.target.wants
      ln -sf /usr/lib/systemd/system/systemd-networkd.service \
        /layer/usr/lib/systemd/system/multi-user.target.wants/systemd-networkd.service
      ln -sf /usr/lib/systemd/system/systemd-resolved.service \
        /layer/usr/lib/systemd/system/multi-user.target.wants/systemd-resolved.service
      ln -sf /usr/lib/systemd/system/sshd.service \
        /layer/usr/lib/systemd/system/multi-user.target.wants/sshd.service
      # Mask systemd-firstboot to prevent interactive credential blocks on tty1
      mkdir -p /layer/etc/systemd/system
      ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service
      # DHCP on all ethernet interfaces
      mkdir -p /layer/usr/lib/systemd/network
      printf '[Match]\nName=en* eth* ens* enp*\n\n[Network]\nDHCP=yes\n' \
        > /layer/usr/lib/systemd/network/80-dhcp.network
      # Allow root login with empty password over SSH (installer is ephemeral)
      mkdir -p /layer/etc/ssh/sshd_config.d
      printf 'PermitRootLogin yes\nPermitEmptyPasswords yes\n' \
        > /layer/etc/ssh/sshd_config.d/installer.conf

      # Bake SSH keys into the root user's authorized_keys in the live environment
      mkdir -p /layer/root/.ssh
      cat > /layer/root/.ssh/authorized_keys << 'SSHKEY'
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPTn9YbnzdPkWSHjfaM8cs3oTmPN5KNqQxF28qIQmoYW jorge.castro@gmail.com
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPzkpPRSOzDwEUwkTxS257lewEBz8za8vMuwUWsFO1sp jorge.castro@gmail.com
      SSHKEY
      chmod 700 /layer/root/.ssh
      chmod 600 /layer/root/.ssh/authorized_keys

      # Create fully automated non-interactive install script
      mkdir -p /layer/usr/sbin
      cat > /layer/usr/sbin/bluefin-autoinstall << 'AUTOINSTALL'
      #!/bin/bash
      set -euo pipefail

      echo "=================================================="
      echo "      BLUEFIN SERVER AUTOMATED INSTALLER"
      echo "=================================================="

      # 1. Detect target disk (prefer smallest NVMe, fallback to smallest non-installer disk)
      echo "Detecting NVMe disks..."
      TARGET_DISK=$(lsblk -dno NAME,SIZE,TYPE | grep nvme | sort -k2 -h | head -n 1 | awk '{print "/dev/"$1}')

      if [ -z "${TARGET_DISK}" ]; then
          echo "No NVMe disk found. Falling back to the smallest virtio/SCSI/SATA disk..."
          # Find the installer disk to exclude it from being formatted
          INSTALLER_DISK=$(lsblk -no PKNAME,LABEL | grep "bluefin-installer-data" | head -n 1 | awk '{print "/dev/"$1}' | sed 's/[0-9]*$//')
          if [ -z "${INSTALLER_DISK}" ]; then
              INSTALLER_DISK=$(lsblk -no PKNAME,PARTLABEL | grep "bluefin-installer-data" | head -n 1 | awk '{print "/dev/"$1}' | sed 's/[0-9]*$//')
          fi
          echo "Live installer source disk identified: ${INSTALLER_DISK}"

          TARGET_DISK=$(lsblk -dno NAME,SIZE,TYPE | grep disk | sort -k2 -h | while read -r name size type; do
              dev_path="/dev/${name}"
              if [ "${dev_path}" != "${INSTALLER_DISK}" ]; then
                  echo "${dev_path}"
                  break
              fi
          done)
      fi

      if [ -z "${TARGET_DISK}" ]; then
          echo "ERROR: No suitable target disk found for automated installation!"
          exit 1
      fi

      echo "Target disk selected: ${TARGET_DISK}"
      echo "Wiping and partitioning ${TARGET_DISK} using systemd-repart..."

      # 2. Run systemd-repart to partition the target disk and copy DDI block-for-block
      systemd-repart --dry-run=no --empty=force --definitions=/usr/lib/repart.d/ "${TARGET_DISK}"

      # Settle udev to make sure partition devices are created
      echo "Settling udev..."
      udevadm settle --timeout=15

      # 3. Detect created partitions
      echo "Detecting created partitions..."
      ESP_DEV=""
      ROOT_DEV=""
      ROOT_PARTUUID=""

      lines=$(lsblk -rno PATH,PARTTYPE,PARTUUID,PARTLABEL "${TARGET_DISK}")
      while read -r path parttype partuuid label; do
          if [ "${parttype}" = "c12a7328-f81f-11d2-ba4b-00a0c93ec93b" ]; then
              ESP_DEV="${path}"
          fi
          if [ "${label}" = "bluefin-server-root-a" ]; then
              ROOT_DEV="${path}"
              ROOT_PARTUUID="${partuuid}"
          fi
      done <<< "${lines}"

      if [ -z "${ESP_DEV}" ] || [ -z "${ROOT_DEV}" ]; then
          echo "ERROR: Failed to detect ESP or ROOT partition on ${TARGET_DISK}!"
          exit 1
      fi

      echo "Detected ESP: ${ESP_DEV}"
      echo "Detected ROOT: ${ROOT_DEV} (PARTUUID: ${ROOT_PARTUUID})"

      # 4. Mount partitions
      echo "Mounting partitions..."
      mkdir -p /mnt/esp /mnt/root
      mount "${ESP_DEV}" /mnt/esp
      mount "${ROOT_DEV}" /mnt/root

      # Set up automatic cleanup on exit (unmount)
      cleanup() {
          echo "Cleaning up mounts..."
          umount /mnt/root || true
          umount /mnt/esp || true
      }
      trap cleanup EXIT

      # 5. Provision user 'jorge' and install SSH keys
      echo "Provisioning user 'jorge'..."
      useradd --root /mnt/root --create-home --groups wheel,sudo --shell /bin/bash jorge

      # Create .ssh directory and write authorized_keys
      mkdir -p /mnt/root/home/jorge/.ssh
      cat > /mnt/root/home/jorge/.ssh/authorized_keys << 'EOF'
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPTn9YbnzdPkWSHjfaM8cs3oTmPN5KNqQxF28qIQmoYW jorge.castro@gmail.com
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPzkpPRSOzDwEUwkTxS257lewEBz8za8vMuwUWsFO1sp jorge.castro@gmail.com
      EOF

      chmod 700 /mnt/root/home/jorge/.ssh
      chmod 600 /mnt/root/home/jorge/.ssh/authorized_keys
      chroot /mnt/root chown -R jorge:jorge /home/jorge/.ssh

      # Enable passwordless sudo for user 'jorge'
      echo "jorge ALL=(ALL) NOPASSWD: ALL" > /mnt/root/etc/sudoers.d/jorge
      chmod 0440 /mnt/root/etc/sudoers.d/jorge

      # Also bake the SSH keys into the root user's authorized_keys in the installed system
      echo "Baking SSH keys into installed root account..."
      mkdir -p /mnt/root/root/.ssh
      cat > /mnt/root/root/.ssh/authorized_keys << 'EOF'
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPTn9YbnzdPkWSHjfaM8cs3oTmPN5KNqQxF28qIQmoYW jorge.castro@gmail.com
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPzkpPRSOzDwEUwkTxS257lewEBz8za8vMuwUWsFO1sp jorge.castro@gmail.com
      EOF
      chmod 700 /mnt/root/root/.ssh
      chmod 600 /mnt/root/root/.ssh/authorized_keys

      # 6. systemd-firstboot for hostname and timezone
      echo "Setting up hostname and timezone..."
      systemd-firstboot --image-root=/mnt/root --hostname=bluefin-server --timezone=UTC || true

      # 7. systemd-boot installation
      echo "Installing systemd-boot..."
      bootctl install --esp-path=/mnt/esp || true

      # 8. Write boot entry
      echo "Writing boot entry..."
      mkdir -p /mnt/esp/loader/entries

      KVER=$(ls /mnt/root/usr/lib/modules | head -n 1)
      if [ -n "${KVER}" ]; then
          cp /mnt/root/boot/vmlinuz "/mnt/esp/vmlinuz-${KVER}"
          VMLINUZ_ENTRY="/vmlinuz-${KVER}"
      else
          cp /mnt/root/boot/vmlinuz /mnt/esp/vmlinuz
          VMLINUZ_ENTRY="/vmlinuz"
      fi

      cat > /mnt/esp/loader/entries/bluefin-server.conf << EOF
      title   Bluefin Server
      linux   ${VMLINUZ_ENTRY}
      options root=PARTUUID=${ROOT_PARTUUID} console=tty0 console=ttyS0,115200 rw
      EOF

      echo "Installation successfully completed!"
      echo "Rebooting machine..."
      sleep 3
      systemctl reboot
      AUTOINSTALL
      chmod +x /layer/usr/sbin/bluefin-autoinstall

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

    # ── Step 4: Build the UKI ────────────────────────────────────────────
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
        --cmdline="systemd.unit=installer.target console=ttyS0,115200 console=tty0 rw" \
        --output=/layer/boot/efi/EFI/Linux/installer.efi
      mkdir -p /layer/boot/efi/EFI/BOOT
      cp /layer/boot/efi/EFI/Linux/installer.efi /layer/boot/efi/EFI/BOOT/BOOTX64.EFI
      ls -lh /layer/boot/efi/EFI/Linux/installer.efi

    # ── Step 5: Decompress DDI payload for embedding ─────────────────────
    # This runs AFTER the initrd cpio is packed (Step 3), so the DDI is NOT
    # included in the initrd. It is placed in /layer temporarily so that
    # systemd-repart's CopyBlocks= (which resolves paths under --root=/layer)
    # can copy it into the installer media data partition.
    - |
      set -eu
      zstd -d /ddi/bluefin-server-ddi-*.raw.zst -o /layer/bluefin-server-ddi.raw
      ls -lh /layer/bluefin-server-ddi.raw

    # ── Step 6: Assemble installer GPT disk image ────────────────────────
    # Two-partition layout:
    #   10-esp.conf:      ESP (1G) — UKI lives here; boots the installer
    #   20-ddi-data.conf: Data (ext4) — bluefin-server-ddi.raw copied here block-for-block
    #
    # At install time, installer.service mounts the data partition to
    # /run/installer/ so systemd-repart can find the DDI at the path
    # expected by repart.d/20-root-a.conf (CopyBlocks=).
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
      SizeMinBytes=768M
      SizeMaxBytes=768M
      RCONF

      cat > /installer-media-repart.d/20-ddi-data.conf << 'RCONF'
      [Partition]
      Type=linux-generic
      Label=bluefin-installer-data
      CopyBlocks=/bluefin-server-ddi.raw
      RCONF

      systemd-repart \
        --empty=create \
        --size=auto \
        --dry-run=no \
        --root=/layer \
        --definitions=/installer-media-repart.d \
        "${OUT}/${FNAME}"
      ls -lh "${OUT}/${FNAME}"

      # Clean up DDI from /layer — it's now in the installer media partition.
      rm -f /layer/bluefin-server-ddi.raw

    # ── Step 7: Compress + checksum ──────────────────────────────────────
    - |
      set -eu
      cd "%{install-root}"
      FNAME="bluefin-server-installer-%{installer-version}.raw"
      zstd --rm -T0 -19 -q "${FNAME}" -o "${FNAME}.zst"
      sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      ls -lh
