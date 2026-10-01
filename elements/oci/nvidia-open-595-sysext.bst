kind: manual
description: |
  Opt-in systemd-sysext with the NVIDIA driver branch 595, open kernel
  modules only (Turing and newer GPUs).

  Output: nvidia-open-595_<image-version>.raw, .raw.zst and SHA256SUMS.
  The modules only load on the kernel they were built against, so the
  sysext is locked to one image like the ZFS sysext:
  extension-release.nvidia-open-595_<image-version> with ID=bluefin-server
  and VERSION_ID=<image-version>.

  Contents: the signed modules under /usr/lib/modules/<kver>/extra/nvidia/
  (no modules.* index: nvidia-load.service loads them through the base
  image's /usr/libexec/bluefin-sysext-modules), the headless userspace, GSP
  firmware and license from nvidia/nvidia-open-595-signed.bst, and the units
  and modprobe/sysusers/tmpfiles drop-ins shared by every flavour
  (files/nvidia/sysext). Recipe: include/nvidia-driver.yml.

(@):
- include/arch.yml
- include/image.yml
- include/nvidia.yml
- include/nvidia-driver.yml
- include/sysext.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/sed.bst
- freedesktop-sdk.bst:components/zstd.bst
- filename: bluefin-server/kernel-modules.bst
  config:
    location: /kernel-modules
- filename: nvidia/nvidia-open-595-signed.bst
  config:
    location: /nvidia-driver

sources:
- kind: local
  path: files/nvidia/sysext
  directory: sysext-src

variables:
  nvidia-flavour: nvidia-open-595
  nvidia-version: "%{nvidia-open-595-version}"
  sysext-name: "nvidia-open-595"
  sysext-image: "nvidia-open-595_%{image-version}"
  sysext-release: "nvidia-open-595_%{image-version}"
  sysext-version: "%{image-version}"
  sysext-architecture: "%{systemd-arch}"

config:
  install-commands:
  - "%{nvidia-sysext-stage}"
  - "%{sysext-pack}"
