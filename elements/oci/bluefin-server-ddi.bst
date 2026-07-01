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
  - freedesktop-sdk.bst:components/zstd.bst
  - filename: bluefin-server/os-stack.bst
    config:
      location: /layer

variables:
  ddi-version: "25.08.13"

config:
  commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      FNAME="bluefin-server-ddi-%{ddi-version}.raw"

      rm -rf /layer/usr/lib/debug
      find /layer -type f -name '*.debug' -delete

      # Sum up all file sizes across all bind mounts in the bwrap sandbox using pure bash arithmetic (no awk/gawk dependency)
      # ponytail: pure bash loop avoids external tool dependency (like awk) and is 100% robust.
      ROOT_BYTES=0
      for size in $(find /layer -type f -printf "%s\n"); do
        ROOT_BYTES=$(( ROOT_BYTES + size ))
      done
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
