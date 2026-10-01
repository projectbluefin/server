kind: manual
description: |
  Produce a systemd-sysext extension image for k0s.

  Output: k0s-<k0s-version>.raw, k0s-<k0s-version>.raw.zst, and SHA256SUMS.
  Contains /usr/bin/k0s, k0scontroller.service and k0sworker.service (picked
  by /etc/k0s/token). The KubeStellar
  appliance (Argo CD, KubeStellar console) is the separate, opt-in
  oci/kubestellar-sysext.bst.

(@):
  - include/arch.yml
  - include/k0s.yml
  - include/sysext.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/erofs-utils.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - filename: k0s/k0s-bin.bst
    config:
      location: /

sources:
  - kind: local
    path: files/k0s/sysext
    directory: sysext-src

variables:
  strip-binaries: ""
  sysext-name: "k0s"
  sysext-image: "k0s-%{k0s-version}"
  # Merged as /run/extensions/k0s.raw (k0s-first-boot.service), so the
  # extension-release name carries no version.
  sysext-release: "k0s"
  sysext-version: "%{k0s-version}"
  sysext-architecture: "%{systemd-arch}"

config:
  install-commands:
    - |
      set -euo pipefail
      mkdir -p sysext/usr/bin sysext/usr/lib/systemd/system
      cp -a /usr/bin/k0s sysext/usr/bin/k0s
      chmod 0755 sysext/usr/bin/k0s
      cp -a sysext-src/k0scontroller.service sysext-src/k0sworker.service sysext/usr/lib/systemd/system/
    - "%{sysext-pack}"
