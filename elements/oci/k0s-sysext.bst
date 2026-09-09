kind: manual
description: |
  Produce a systemd-sysext extension image for k0s.

  Output: k0s-<k0s-version>.raw, k0s-<k0s-version>.raw.zst, and SHA256SUMS.
  Contains /usr/bin/k0s, k0scontroller.service, tmpfiles.d/k0s-manifests.conf,
  and /usr/share/k0s/manifests/ (Argo CD and KubeStellar).

(@):
  - include/arch.yml
  - include/k0s.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/erofs-utils.bst
  - freedesktop-sdk.bst:components/xz.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - filename: k0s/k0s-bin.bst
    config:
      location: /

sources:
  - kind: local
    path: files/k0s/sysext
    directory: sysext-src
  - kind: local
    path: files/k0s/manifests
    directory: manifests-src
  - kind: local
    path: files/k0s/kiosk
    directory: kiosk-src
  - kind: local
    path: files/os/issue.d/40-kubestellar.issue
    directory: issue-src

variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      FNAME="k0s-%{k0s-version}.raw"

      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/oci/k0s-sysext.bst only supports x86_64 (got %{arch})" >&2
        exit 1
      fi

      mkdir -p sysext/usr/bin
      mkdir -p sysext/usr/lib/systemd/system
      mkdir -p sysext/usr/lib/extension-release.d
      mkdir -p sysext/usr/lib/tmpfiles.d
      mkdir -p sysext/usr/lib/issue.d
      mkdir -p sysext/usr/share/k0s/manifests
      mkdir -p sysext/usr/share/k0s/kiosk
      mkdir -p "${OUT}"

      # Stage k0s binary
      cp -a /usr/bin/k0s sysext/usr/bin/k0s
      chmod 0755 sysext/usr/bin/k0s

      # Stage systemd service
      cp -a sysext-src/k0scontroller.service sysext/usr/lib/systemd/system/

      # Stage extension release metadata
      cp -a sysext-src/extension-release.k0s sysext/usr/lib/extension-release.d/
      echo "VERSION_ID=%{k0s-version}" >> sysext/usr/lib/extension-release.d/extension-release.k0s
      echo "ARCHITECTURE=%{systemd-arch}" >> sysext/usr/lib/extension-release.d/extension-release.k0s

      # Stage tmpfiles seeding configuration
      cp -a sysext-src/k0s-manifests.conf sysext/usr/lib/tmpfiles.d/

      # Stage console issue banner
      cp -a issue-src/40-kubestellar.issue sysext/usr/lib/issue.d/

      # Stage manifest stacks
      cp -a manifests-src/* sysext/usr/share/k0s/manifests/

      # Stage Console kiosk proxy assets.
      cp -a kiosk-src/. sysext/usr/share/k0s/kiosk/

      # Build EROFS image
      mkfs.erofs -d0 "${OUT}/${FNAME}" sysext

      # Compress release asset
      zstd -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"

      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
