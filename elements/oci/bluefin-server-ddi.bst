kind: script
description: |
  Produce the Bluefin Server OS DDI payload filesystem image.

  Output: bluefin-server-ddi-<ver>.raw.zst + SHA256SUMS

  The output .raw is a filesystem image consumed by installer repart config:
  files/installer/repart.d/20-root-a.conf via CopyBlocks=.

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/e2fsprogs.bst
  - freedesktop-sdk.bst:components/findutils.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - filename: bluefin-server/os-stack.bst
    config:
      location: /layer

variables:
  ddi-version: "0.1.0"

config:
  commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      FNAME="bluefin-server-ddi-%{ddi-version}.raw"

      rm -rf /layer/usr/lib/debug
      find /layer -type f -name '*.debug' -delete

      # Reserve overhead for metadata and future growth.
      set -- $(du -sk /layer)
      ROOT_BYTES=$(( $1 * 1024 ))
      TARGET_BYTES=$(( ROOT_BYTES + (2 * 1024 * 1024 * 1024) ))
      if [ "$TARGET_BYTES" -lt $((8 * 1024 * 1024 * 1024)) ]; then
        TARGET_BYTES=$((8 * 1024 * 1024 * 1024))
      fi

      BLOCKS=$(( TARGET_BYTES / 4096 ))
      mkfs.ext4 -F -L bluefin-roota -d /layer "${OUT}/${FNAME}" "${BLOCKS}"

      zstd --rm -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"
      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
