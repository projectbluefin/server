kind: manual
description: |
  Import the Flatcar LTS Linux Kernel binary (vmlinuz) and matching module tree.
  Contains all upstream Flatcar kernel patches (EFI secure boot lockdown, partition UUID uevents,
  reproducible pahole builds, relative srctree kbuild).
  Pinned in lockstep with the Flatcar release version defined in include/flatcar.yml.

(@):
  - include/arch.yml
  - include/flatcar.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/tar.bst
  - freedesktop-sdk.bst:components/gzip.bst
  - freedesktop-sdk.bst:components/xz.bst
  - freedesktop-sdk.bst:components/findutils.bst

variables:
  strip-binaries: ""

sources:
  - kind: remote
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar_production_image.vmlinuz
    ref: fe0b7ef1f9f98acc00e1db22937cdc57456df860a372fdc8eb806298f767b676
  - kind: remote
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-container.tar.gz
    ref: c533ff576e128d11ce240e01f818c358d75b9ff118b2dd9199fbf4684547a32c
  - kind: local
    path: patches/flatcar-kernel
    directory: patches

config:
  install-commands:
    - |
      set -euo pipefail

      TARGET_MODDIR="%{install-root}/usr/lib/modules/%{flatcar-kver}"
      mkdir -p "${TARGET_MODDIR}"

      # Install the kernel binary
      install -D -m 0644 flatcar_production_image.vmlinuz "${TARGET_MODDIR}/vmlinuz"

      # Extract modules from container rootfs
      tar -zxvf flatcar-container.tar.gz \
        --strip-components=4 \
        -C "${TARGET_MODDIR}" \
        "./usr/lib/modules/%{flatcar-kver}"

      # Uncompress .xz modules so dracut, depmod, and kmod can handle them consistently
      find "${TARGET_MODDIR}" -type f -name '*.ko.xz' -exec unxz {} +

      # Strip vmlinux and System.map if present to save image footprint
      rm -f "${TARGET_MODDIR}/vmlinux" "${TARGET_MODDIR}/System.map"

      # Stage Flatcar kernel patchset for reference and downstream builds
      mkdir -p "%{install-root}/usr/src/flatcar-kernel-patches"
      cp -a patches/*.patch "%{install-root}/usr/src/flatcar-kernel-patches/"
