kind: manual
description: |
  Import the Flatcar podman system extension (sysext).
  Provides the podman container CLI, replacing the FSDK podman component in the
  OS payload (projectbluefin/server#127, hard rule 4: no container runtime in
  the base DDI). Only the raw squashfs is staged under /usr/lib/sysexts so
  systemd-sysext attaches it at runtime on a booted image; the runtime is not
  extracted into the base DDI.

(@):
  - include/arch.yml
  - include/flatcar.yml

build-depends:
  - base/base-stack.bst

sources:
  - kind: remote
    # podman ships flat; containerd/docker ship under rootfs-included-sysexts/.
    # All six upstream permutations were checked — the other three 404.
    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-podman.raw
    ref: bc8c6777ab9dee286eb1f70a1605a880fcc5199246d87f9c92f00d880194d72b

config:
  install-commands:
    - |
      set -euo pipefail

      # Stage the raw squashfs sysext under /usr/lib/sysexts so systemd-sysext
      # attaches it at runtime on a booted image. The runtime is not extracted
      # into the base DDI (hard rule 4).
      mkdir -p "%{install-root}/usr/lib/sysexts"
      install -D -m 0644 flatcar-podman.raw "%{install-root}/usr/lib/sysexts/podman.raw"
