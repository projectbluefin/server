kind: manual
description: |
  NVIDIA driver branch 595 (production): the open kernel modules built from
  the .run's kernel-open/ tree against the FSDK kernel, unsigned, plus the
  headless userspace, GSP firmware and license. Recipe:
  include/nvidia-driver.yml; version and sha256: include/nvidia.yml.

  No runtime `depends:`: nvidia/nvidia-open-595-signed.bst stages this
  artifact at a private location.

(@):
- include/nvidia.yml
- include/nvidia-driver.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/buildsystem-make.bst
- freedesktop-sdk.bst:components/linux.bst
- freedesktop-sdk.bst:components/elfutils.bst
- freedesktop-sdk.bst:components/kmod.bst
- freedesktop-sdk.bst:components/tar.bst
- freedesktop-sdk.bst:components/zstd.bst

sources:
- kind: remote
  url: nvidia_download:XFree86/Linux-x86_64/%{nvidia-version}/NVIDIA-Linux-x86_64-%{nvidia-version}.run
  ref: "%{nvidia-open-595-sha256}"

variables:
  nvidia-flavour: nvidia-open-595
  nvidia-version: "%{nvidia-open-595-version}"

config:
  build-commands:
  - "%{nvidia-driver-build}"
  install-commands:
  - "%{nvidia-driver-install}"
