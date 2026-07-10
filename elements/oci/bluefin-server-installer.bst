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

  The installer UI is systemd-sysinstall, a native systemd terminal-based
  interactive installer. It prompts for the target disk, partitions it using
  systemd-repart, copies the XFS DDI filesystem, registers the boot loader via
  bootctl, and reboots.

  Build pipeline:
    1. Add /init symlink + mount points
    2. Link default.target -> system-install.target
    3. Pack rootfs as newc cpio + gzip -> installer.cpio.gz
    4. ukify build: kernel + cpio.gz -> installer.efi (unsigned UKI)
    5. Decompress DDI payload into /layer for embedding (after cpio, not in initrd)
    6. systemd-repart --empty=create: assemble two-partition GPT disk
       (ESP with UKI + data partition with embedded DDI payload)
    7. Compress final disk as .raw.zst + SHA256SUMS for GitHub Releases

build-depends:
  # Toolchain for assembly
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/dracut.bst
  - freedesktop-sdk.bst:components/cpio.bst      # newc cpio archive creation
  - freedesktop-sdk.bst:components/findutils.bst  # find for cpio pipe
  # grep/sed are required by dracut/dracut-install even though our commands don't name them.
  - freedesktop-sdk.bst:components/grep.bst
  - freedesktop-sdk.bst:components/sed.bst
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
  - filename: bluefin-server/os-rootfs.bst
    config:
      location: /target-root

variables:
  installer-version: "%{release-version}"

config:
  commands:
    # ── Step 1: Prepare the initrd rootfs ───────────────────────────────
    # /init is required by the Linux initrd protocol (kernel hands control
    # to /init as PID 1). For systemd-native initrds this is a symlink.
    - |
      set -eu
      # Ensure critical tools are present in the staged rootfs before packing
      # ponytail: fail fast if critical dependencies are missing, preventing broken images
      for tool in udevadm lsblk systemd-repart bootctl systemd-sysinstall sshd; do
        if ! [ -x "/layer/usr/bin/${tool}" ] && ! [ -x "/layer/usr/sbin/${tool}" ]; then
          echo "ERROR: Critical tool '${tool}' is missing from the staged rootfs at /layer!" >&2
          exit 1
        fi
      done
      if [ ! -f /layer/usr/lib/systemd/system/sshd.service ]; then
        echo "ERROR: sshd.service is missing from the staged rootfs at /layer!" >&2
        exit 1
      fi

      # systemd-native initrd: /init -> PID 1
      ln -sf usr/lib/systemd/systemd /layer/init
      # Mount points needed by the installer service
      mkdir -p /layer/efi /layer/mnt/esp /layer/mnt/root /layer/run/installer
      mkdir -p /layer/usr/lib/bluefin-server
      mkdir -p /target-root/boot/EFI/Linux /tmp /var/tmp
      KVER="$(basename "$(find /target-root/usr/lib/modules -mindepth 1 -maxdepth 1 -type d | head -n1)")"
      if [ -z "${KVER}" ]; then
        echo "ERROR: no kernel module tree found under /target-root/usr/lib/modules" >&2
        exit 1
      fi
      depmod -b /target-root "${KVER}"
      # Regenerate dynamic linker cache inside the build container so dracut-install can find system libraries (e.g. libc.so.6, libgcc_s.so.1)
      ldconfig
      # Run dracut in generic (non-hostonly) mode and explicitly add XFS and VirtIO block/scsi storage drivers.
      # Since we build inside a container sandbox, dracut won't detect the VM virtual disks automatically
      # and will produce an unbootable/panicking host-only initrd unless forced.
      dracut -v --reproducible --no-machineid --no-hostonly \
        --add-drivers "virtio virtio_blk virtio_pci virtio_scsi xfs" \
        --filesystems "xfs vfat" \
        --kmoddir "/target-root/usr/lib/modules/${KVER}" \
        --kernel-image /target-root/boot/vmlinuz \
        --kver "${KVER}" \
        --kernel-cmdline "rw console=ttyS0,115200 console=tty0" \
        /tmp/bluefin-server-target.initramfs
      ukify build \
        --linux=/target-root/boot/vmlinuz \
        --initrd=/tmp/bluefin-server-target.initramfs \
        --cmdline="rw console=ttyS0,115200 console=tty0" \
        --output=/target-root/boot/EFI/Linux/bluefin-server.efi
      cp /target-root/boot/EFI/Linux/bluefin-server.efi /layer/usr/lib/bluefin-server/bluefin-server.efi
      # System users for networkd/resolved
      printf 'systemd-network:x:998:998:systemd Network Management:/run/systemd:/usr/sbin/nologin\nsystemd-resolve:x:997:997:systemd Resolver:/run/systemd:/usr/sbin/nologin\n' >> /layer/etc/passwd
      printf 'systemd-network:x:998:\nsystemd-resolve:x:997:\n' >> /layer/etc/group
      # Enable sysusers plus the services needed on the live installer target.
      mkdir -p /layer/usr/lib/systemd/system/sysinit.target.wants
      ln -sf /usr/lib/systemd/system/systemd-sysusers.service \
        /layer/usr/lib/systemd/system/sysinit.target.wants/systemd-sysusers.service
      mkdir -p /layer/usr/lib/systemd/system/system-install.target.wants
      ln -sf /usr/lib/systemd/system/systemd-networkd.service \
        /layer/usr/lib/systemd/system/system-install.target.wants/systemd-networkd.service
      ln -sf /usr/lib/systemd/system/systemd-resolved.service \
        /layer/usr/lib/systemd/system/system-install.target.wants/systemd-resolved.service
      ln -sf /usr/lib/systemd/system/sshd.service \
        /layer/usr/lib/systemd/system/system-install.target.wants/sshd.service
      # Mask systemd-firstboot to prevent interactive credential blocks on tty1
      mkdir -p /layer/etc/systemd/system
      ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service

      # Write root hash file
      echo -n '$6$ZbsnFo0smWIQ40GX$ei//Njn0kIsfUrXY9Ty7.jJt2tTgmHlpoZ/amNdKlArtqWYXyup/kScL3O5t.JTP2taesR0.9QktIJiuQvuEI/' > /layer/etc/root_hash
      chmod 600 /layer/etc/root_hash

      # Write the installer wrapper script
      cat > /layer/usr/bin/bluefin-sysinstall << 'EOF'
      #!/bin/bash
      set -euo pipefail

      # Check for TPM presence and warn/fail
      if [ ! -e /sys/class/tpm/tpm0 ] && [ ! -e /sys/class/tpm/tpm_bios ]; then
        echo "WARNING: No TPM2 device detected. System credentials will NOT be cryptographically protected." >&2
      fi

      # Auto-detect target disk for unattended install (any raw disk of type "disk" that is not the installer, is not read-only, and has size > 0)
      TARGET_DISK=""
      INSTALLER_PART="$(readlink -f /dev/disk/by-partlabel/bluefin-installer-data 2>/dev/null || true)"

      while read -r name type ro size; do
        [ "${type}" = "disk" ] || continue
        [ "${ro}" = "0" ] || continue
        [ "${size}" -gt 0 ] || continue

        # Skip the disk containing the installer partition
        if [ -n "${INSTALLER_PART}" ] && [[ "${INSTALLER_PART}" == "${name}"* ]]; then
          continue
        fi

        TARGET_DISK="${name}"
        break
      done < <(lsblk -p -d -n -o NAME,TYPE,RO,SIZE -b)

      # Check for unattended in kernel command line
      CMDLINE="$(cat /proc/cmdline 2>/dev/null || true)"
      if [[ " ${CMDLINE} " == *" unattended "* ]]; then
        echo "==> Running in UNATTENDED mode..."
        if [ -n "${TARGET_DISK}" ]; then
          echo "==> Auto-detected target disk: ${TARGET_DISK}"
          exec /usr/bin/systemd-sysinstall \
            --kernel=/usr/lib/bluefin-server/bluefin-server.efi \
            --erase=yes \
            --confirm=no \
            --summary=no \
            --variables=yes \
            --reboot=no \
            --mute-console=yes \
            --load-credential=passwd.hashed-password.root:/etc/root_hash \
            "${TARGET_DISK}" < /dev/null
        else
          echo "ERROR: No suitable target disk found for unattended installation!" >&2
          exit 1
        fi
      else
        echo "==> Running in INTERACTIVE mode..."
        exec /usr/bin/systemd-sysinstall \
          --kernel=/usr/lib/bluefin-server/bluefin-server.efi \
          --variables=yes \
          --reboot=yes \
          --mute-console=yes \
          --copy-locale=yes \
          --copy-keymap=yes \
          --copy-timezone=yes \
          --load-credential=passwd.hashed-password.root:/etc/root_hash
      fi
      EOF
      chmod +x /layer/usr/bin/bluefin-sysinstall

      mkdir -p /layer/etc/systemd/system/systemd-sysinstall.service.d
      cat > /layer/etc/systemd/system/systemd-sysinstall.service.d/override.conf << 'EOF'
      [Unit]
      SuccessAction=poweroff
      FailureAction=poweroff

      [Service]
      ExecStart=
      ExecStart=/usr/bin/bluefin-sysinstall
      EOF
      # DHCP on all ethernet interfaces
      mkdir -p /layer/usr/lib/systemd/network
      printf '[Match]\nName=en* eth* ens* enp*\n\n[Network]\nDHCP=yes\n' \
        > /layer/usr/lib/systemd/network/80-dhcp.network
      # Allow root login via key-based authentication only over SSH (installer is ephemeral)
      mkdir -p /layer/etc/ssh/sshd_config.d
      printf 'PermitRootLogin prohibit-password\nPasswordAuthentication no\n' \
        > /layer/etc/ssh/sshd_config.d/installer.conf

      # Bake SSH keys into the root user's authorized_keys in the live environment
      mkdir -p /layer/root/.ssh
      cat > /layer/root/.ssh/authorized_keys << 'SSHKEY'
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPTn9YbnzdPkWSHjfaM8cs3oTmPN5KNqQxF28qIQmoYW jorge.castro@gmail.com
      ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIPzkpPRSOzDwEUwkTxS257lewEBz8za8vMuwUWsFO1sp jorge.castro@gmail.com
      SSHKEY
      chmod 700 /layer/root/.ssh
      chmod 600 /layer/root/.ssh/authorized_keys

    # ── Step 2: Wire default.target -> system-install.target ────────────
    - |
      set -eu
      if [ ! -f /layer/usr/lib/systemd/system/system-install.target ]; then
        echo "ERROR: system-install.target is missing from the staged rootfs! FSDK systemd must be version 261 or later." >&2
        exit 1
      fi
      if [ ! -L /layer/usr/lib/systemd/system/system-install.target.wants/systemd-sysinstall.service ]; then
        echo "ERROR: system-install.target.wants/systemd-sysinstall.service is missing from the staged rootfs! FSDK systemd must be built with -Dsysinstall=true." >&2
        exit 1
      fi
      if [ ! -f /layer/etc/systemd/system/sshd.service.d/10-hostkeys.conf ]; then
        echo "ERROR: sshd host-key drop-in is missing from the staged rootfs!" >&2
        exit 1
      fi
      if [ ! -f /layer/usr/lib/bluefin-server/bluefin-server.efi ]; then
        echo "ERROR: target UKI is missing from the staged rootfs!" >&2
        exit 1
      fi
      rm -f /layer/usr/lib/systemd/system/default.target
      ln -sf system-install.target \
        /layer/usr/lib/systemd/system/default.target

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
        | gzip -9 -c > /installer.cpio.gz
      ls -lh /installer.cpio.gz

    # ── Step 4: Build the UKI ────────────────────────────────────────────
    # Unsigned UKI — acceptable for USB installer media. Secure Boot
    # signing can be layered on by passing --secureboot-private-key /
    # --secureboot-certificate if keys are injected at CI time.
    - |
      set -eu
      mkdir -p /layer/boot/efi/EFI/BOOT
      ukify build \
        --linux="/layer/boot/vmlinuz" \
        --initrd=/installer.cpio.gz \
        --cmdline="systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended" \
        --output=/layer/boot/efi/EFI/BOOT/BOOTX64.EFI
      ls -lh /layer/boot/efi/EFI/BOOT/BOOTX64.EFI

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
    #   20-ddi-data.conf: Data (XFS) — bluefin-server-ddi.raw copied here block-for-block
    #
    # At install time, systemd-sysinstall mounts the data partition to
    # locate the DDI at the path expected by repart.d/20-root-a.conf (CopyBlocks=).
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
      SizeMinBytes=1024M
      SizeMaxBytes=1024M
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

      # Also export the target UKI (.efi) for GitHub Releases and systemd-sysupdate
      cp /layer/usr/lib/bluefin-server/bluefin-server.efi "bluefin-server-%{installer-version}.efi"

      sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      sha256sum --binary "bluefin-server-%{installer-version}.efi" >> SHA256SUMS
      ls -lh
