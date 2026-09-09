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

      KVER="$(basename "$(find /layer/usr/lib/modules -mindepth 1 -maxdepth 1 -type d | head -n1)")"
      if [ -z "${KVER}" ]; then
        echo "ERROR: no target kernel module tree found under /layer/usr/lib/modules" >&2
        exit 1
      fi
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

      # Ensure standard /etc/hosts exists for container runtimes (containerd/podman)
      printf '127.0.0.1   localhost\n::1         localhost ip6-localhost ip6-loopback\n' > /layer/etc/hosts

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
