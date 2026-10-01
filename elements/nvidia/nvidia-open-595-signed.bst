kind: manual
description: |
  nvidia/nvidia-open-595.bst with every kernel module signed (sha512) by our
  module key (files/boot-keys/linux-module-cert.key) and zstd-compressed, so
  the lockdown=integrity FSDK kernel accepts them. Same signing steps as
  zfs/openzfs-signed.bst. No runtime `depends:`, so the sysext stages
  exactly these files.

(@):
- include/nvidia.yml
- include/nvidia-driver.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
- freedesktop-sdk.bst:components/findutils.bst
- freedesktop-sdk.bst:components/kmod.bst
- freedesktop-sdk.bst:components/openssl.bst
- freedesktop-sdk.bst:components/sign-file.bst
- freedesktop-sdk.bst:components/zstd.bst
- bluefin-server/keys/boot-keys.bst
- filename: nvidia/nvidia-open-595.bst
  config:
    location: /nvidia-driver

variables:
  nvidia-flavour: nvidia-open-595
  nvidia-version: "%{nvidia-open-595-version}"

config:
  install-commands:
  - "%{nvidia-sign}"
