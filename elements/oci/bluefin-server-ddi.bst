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
  ddi-version: "%{release-version}"

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
      depmod -b /layer "${KVER}"

      # Stage extracted CA certificate bundle into target DDI rootfs
      mkdir -p /layer/etc/pki/ca-trust/extracted /layer/etc/ssl/certs /layer/etc/pki/tls/certs
      cp -a /etc/pki/ca-trust/extracted/* /layer/etc/pki/ca-trust/extracted/
      ln -sf /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /layer/etc/ssl/certs/ca-certificates.crt
      ln -sf /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /layer/etc/pki/tls/certs/ca-bundle.crt
      ln -sf /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem /layer/etc/pki/tls/cert.pem

      # Mask systemd-firstboot to prevent interactive prompts on headless first boot
      mkdir -p /layer/etc/systemd/system
      ln -sf /dev/null /layer/etc/systemd/system/systemd-firstboot.service

      # Mask audit-rules to prevent failure on shell-free OS (augenrules requires /bin/sh)
      ln -sf /dev/null /layer/etc/systemd/system/audit-rules.service

      # Ensure standard /etc/hosts exists for container runtimes (containerd/podman)
      printf '127.0.0.1   localhost\n::1         localhost ip6-localhost ip6-loopback\n' > /layer/etc/hosts

      # Ensure persistent /var is mounted from its partition label
      printf '/dev/disk/by-partlabel/var /var xfs defaults 0 0\n' > /layer/etc/fstab

      # Ensure all standard virtual, serial, and hypervisor consoles allow root login
      printf 'tty0\ntty1\ntty2\ntty3\ntty4\ntty5\ntty6\nttyS0\nttyS1\nconsole\nhvc0\n' > /layer/etc/securetty

      # Seed default root password 'bluefin' into /etc/shadow for console and ssh login
      mkdir -p /layer/etc
      printf 'root:$6$bluefin123$o2pQjPN1n3ZCnYUROlA01xAdnGO7mhVRAVw98x4xc8LAUIJv7b44bBNoER6fM4P.rrj4ePYFfkx9WvZICU8nt/:19700:0:99999:7:::\n' > /layer/etc/shadow
      chmod 0600 /layer/etc/shadow
      printf 'root:x:0:0:root:/root:/bin/bash\n' > /layer/etc/passwd
      chmod 0644 /layer/etc/passwd
      printf 'root:x:0:\n' > /layer/etc/group
      chmod 0644 /layer/etc/group

      # Pre-generate SSH host keys for first boot remote diagnostics
      mkdir -p /layer/etc/ssh
      ssh-keygen -q -N "" -t ed25519 -f /layer/etc/ssh/ssh_host_ed25519_key
      ssh-keygen -q -N "" -t rsa -b 3072 -f /layer/etc/ssh/ssh_host_rsa_key
      chmod 0600 /layer/etc/ssh/ssh_host_*_key
      chmod 0644 /layer/etc/ssh/ssh_host_*.pub

      # Sum actual file sizes across bind mounts (du -sb reports content bytes, not overlay blocks).
      ROOT_BYTES=$(du -sb /layer | cut -f1)
      echo "Computed root filesystem size: ${ROOT_BYTES} bytes"

      # 25% overhead and 100MB margin for XFS metadata, journal, and structures.
      # ponytail: 25% overhead + 100MB margin for XFS.
      TARGET_BYTES=$(( ROOT_BYTES + ROOT_BYTES / 4 + 100 * 1024 * 1024 ))

      # Align TARGET_BYTES to 4096-byte boundary (multiple of 512/4096) for sector compatibility
      # ponytail: sector alignment is required by systemd-repart CopyBlocks=.
      TARGET_BYTES=$(( (TARGET_BYTES + 4095) / 4096 * 4096 ))

      # Pre-allocate the raw file to the exact target size.
      # ponytail: pre-allocating is the standard way to enforce the target size of mkfs.xfs.
      truncate -s "${TARGET_BYTES}" "${OUT}/${FNAME}"

      echo "Allocating XFS image of ${TARGET_BYTES} bytes"
      mkfs.xfs -f -L bluefin-root -p /layer "${OUT}/${FNAME}"

      zstd --rm -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"
      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
