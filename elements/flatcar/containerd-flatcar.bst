kind: manual
description: |
  Import the Flatcar containerd system extension (sysext).
  Provides the containerd runtime and CLI, published by Flatcar as a
  rootfs-included sysext (projectbluefin/server#127). Only the raw squashfs is
  staged under /usr/lib/sysexts so systemd-sysext attaches it at runtime; the
  runtime is not extracted into the base DDI (hard rule 4).

(@):
  - include/arch.yml
  - include/flatcar.yml

build-depends:
  - base/base-stack.bst

sources:
  - kind: remote
    # rootfs-included-sysexts/ — podman ships flat instead. All six upstream
    # permutations were checked — the other three 404.
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/rootfs-included-sysexts/containerd-flatcar.raw
    ref: 78e38344ac490004b9fa4c7da38bbfcffc393146aa990379aff7b5c09589f809

config:
  install-commands:
    - |
      set -euo pipefail

      # Stage the raw squashfs sysext under /usr/lib/sysexts so systemd-sysext
      # attaches it at runtime on a booted image. The runtime is not extracted
      # into the base DDI (hard rule 4).
      mkdir -p "%{install-root}/usr/lib/sysexts"
      install -D -m 0644 containerd-flatcar.raw "%{install-root}/usr/lib/sysexts/containerd.raw"
