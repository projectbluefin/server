kind: script
description: |
  Produce the Bluefin Server OS DDI payload filesystem image.

  Output: bluefin-server-ddi-<ver>.raw.zst + SHA256SUMS

  The output .raw is a filesystem image consumed by installer repart config:
  files/installer/repart.d/20-root-a.conf via CopyBlocks=.

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/xfsprogs.bst
  - freedesktop-sdk.bst:components/findutils.bst
  - freedesktop-sdk.bst:components/kmod.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - freedesktop-sdk.bst:components/openssh.bst
  - filename: bluefin-server/os-stack.bst
    config:
      location: /layer

variables:
  ddi-version: "%{flatcar-version}"

config:
  commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      FNAME="bluefin-server-ddi-%{ddi-version}.raw"

      rm -rf /layer/usr/lib/debug
      find /layer -type f -name '*.debug' -delete
      find /layer -type f -name '*.a' -delete

      KVER="$(basename "$(find /layer/usr/lib/modules -mindepth 1 -maxdepth 1 -type d | head -n1)")"
      if [ -z "${KVER}" ]; then
        echo "ERROR: no target kernel module tree found under /layer/usr/lib/modules" >&2
        exit 1
      fi
      rm -f "/layer/usr/lib/modules/${KVER}/vmlinux" "/layer/usr/lib/modules/${KVER}/System.map"
      depmod -b /layer/usr "${KVER}"

      # Stage extracted CA certificate bundle into target DDI rootfs
      # Remote execution may hard-link the staged CA files to the build root;
      # replace the target tree before copying rather than copying onto itself.
      rm -rf /layer/etc/pki/ca-trust/extracted
      mkdir -p /layer/etc/pki/ca-trust/extracted /layer/etc/ssl/certs /layer/etc/pki/tls/certs
      cp -a /etc/pki/ca-trust/extracted/* /layer/etc/pki/ca-trust/extracted/
      ln -sf /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /layer/etc/ssl/certs/ca-certificates.crt
      ln -sf /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /layer/etc/pki/tls/certs/ca-bundle.crt
      ln -sf /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /layer/etc/pki/tls/cert.pem

      # Mask both first-boot wizards to prevent interactive prompts on headless
      # first boot: systemd-firstboot.service prompts for locale/keymap/timezone/
      # root password, and systemd-homed-firstboot.service runs
      # `homectl firstboot --prompt-new-user`. Both are ConditionFirstBoot=yes,
      # read StandardInput=tty, and order themselves before
      # first-boot-complete.target, so either one blocks the boot transaction
      # forever on a console nobody is attached to.
      mkdir -p /layer/etc/systemd/system
      ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service
      ln -sf /dev/null /layer/etc/systemd/system/systemd-homed-firstboot.service

      # Mask audit-rules to prevent failure on shell-free OS (augenrules requires /bin/sh)
      ln -sf /dev/null /layer/etc/systemd/system/audit-rules.service

      # Silence kernel and audit log spam on the console
      mkdir -p /layer/etc/systemd/journald.conf.d /layer/etc/sysctl.d
      printf '[Journal]\nForwardToConsole=no\nMaxLevelConsole=warning\n' > /layer/etc/systemd/journald.conf.d/10-console.conf
      printf 'kernel.printk = 3 4 1 3\n' > /layer/etc/sysctl.d/10-console.conf
      ln -sf /dev/null /layer/etc/systemd/system/systemd-journald-audit.socket

      # Ensure standard /etc/hosts exists for container runtimes (containerd/podman)
      printf '127.0.0.1   localhost\n::1         localhost ip6-localhost ip6-loopback\n' > /layer/etc/hosts

      # Ensure persistent /var is mounted from its partition label
      printf '/dev/disk/by-partlabel/var /var xfs defaults 0 0\n' > /layer/etc/fstab

      # Ensure all standard virtual, serial, and hypervisor consoles allow root login
      printf 'tty0\ntty1\ntty2\ntty3\ntty4\ntty5\ntty6\nttyS0\nttyS1\nconsole\nhvc0\n' > /layer/etc/securetty

      # Seed default root password 'bluefin' for local console bring-up only.
      # The last-change field is 0 (equivalent to `chage -d 0 root`), so the
      # password is expired at first login and the console forces a per-install
      # rotation before any shell is granted. The seeded credential must never
      # be usable over the network: the sshd drop-in sets PermitRootLogin
      # prohibit-password and PasswordAuthentication no.
      mkdir -p /layer/etc
      printf 'root:$6$bluefin123$o2pQjPN1n3ZCnYUROlA01xAdnGO7mhVRAVw98x4xc8LAUIJv7b44bBNoER6fM4P.rrj4ePYFfkx9WvZICU8nt/:0:0:99999:7:::\n' > /layer/etc/shadow
      chmod 0600 /layer/etc/shadow
      printf 'root:x:0:0:root:/root:/bin/bash\n' > /layer/etc/passwd
      chmod 0644 /layer/etc/passwd
      printf 'root:x:0:\n' > /layer/etc/group
      chmod 0644 /layer/etc/group

      # SSH host keys are generated per device on first sshd start
      # (ssh-host-keygen.service), never at build time: this DDI is published
      # as a public release asset, so baked-in keys would expose every
      # deployment's host private keys.
      mkdir -p /layer/etc/ssh

      # Sum actual file sizes across bind mounts (du -sb reports content bytes, not overlay blocks).
      ROOT_BYTES=$(du -sb /layer | cut -f1)
      echo "Computed root filesystem size: ${ROOT_BYTES} bytes"

      # 30% overhead and 250MB margin for XFS metadata, journal, and structures.
      TARGET_BYTES=$(( ROOT_BYTES + ROOT_BYTES * 3 / 10 + 250 * 1024 * 1024 ))

      # Align TARGET_BYTES to 4096-byte boundary (multiple of 512/4096) for sector compatibility
      # ponytail: sector alignment is required by systemd-repart CopyBlocks=.
      TARGET_BYTES=$(( (TARGET_BYTES + 4095) / 4096 * 4096 ))

      # Pre-allocate the raw file to the exact target size.
      # ponytail: pre-allocating is the standard way to enforce the target size of mkfs.xfs.
      truncate -s "${TARGET_BYTES}" "${OUT}/${FNAME}"

      echo "Allocating XFS image of ${TARGET_BYTES} bytes"
      mkfs.xfs -f -L bluefin-root -m reflink=0,rmapbt=0 -n parent=0 -i exchange=0 -p /layer "${OUT}/${FNAME}"

      zstd --rm -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"
      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
