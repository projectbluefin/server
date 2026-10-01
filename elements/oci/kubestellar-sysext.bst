kind: manual
description: |
  Opt-in systemd-sysext with the KubeStellar appliance for k0s: Argo CD and
  KubeStellar manifests, the loopback kiosk proxy assets, and the kubeflex
  secret generators, seeded by kubestellar-seed.service before
  k0scontroller.service starts. Requires the k0s sysext.

  Output: kubestellar_<image-version>.raw, .raw.zst, and SHA256SUMS. Locked to
  one image version like the ZFS sysext and updated in lock-step with the OS
  through the `kubestellar` sysupdate feature.

(@):
  - include/image.yml
  - include/sysext.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/erofs-utils.bst
  - freedesktop-sdk.bst:components/zstd.bst

sources:
  - kind: local
    path: files/kubestellar/sysext
    directory: sysext-src
  - kind: local
    path: files/k0s/manifests
    directory: manifests-src
  - kind: local
    path: files/k0s/kiosk
    directory: kiosk-src
  - kind: local
    path: files/k0s/kubeflex
    directory: kubeflex-src

variables:
  strip-binaries: ""
  sysext-name: "kubestellar"
  sysext-image: "kubestellar_%{image-version}"
  sysext-release: "kubestellar_%{image-version}"
  sysext-version: "%{image-version}"
  # Manifests, kiosk assets and shell scripts only.
  sysext-architecture: ""

config:
  install-commands:
    - |
      set -euo pipefail
      root=sysext/usr
      mkdir -p "${root}/lib/systemd/system/k0scontroller.service.wants" \
        "${root}/lib/tmpfiles.d" "${root}/lib/issue.d" \
        "${root}/share/k0s/manifests" "${root}/share/k0s/kiosk" "${root}/share/k0s/kubeflex"
      cp -a sysext-src/kubestellar-seed.service "${root}/lib/systemd/system/"
      ln -s ../kubestellar-seed.service "${root}/lib/systemd/system/k0scontroller.service.wants/kubestellar-seed.service"
      cp -a sysext-src/k0s-manifests.conf "${root}/lib/tmpfiles.d/"
      cp -a sysext-src/40-kubestellar.issue "${root}/lib/issue.d/"
      cp -a manifests-src/* "${root}/share/k0s/manifests/"
      cp -a kiosk-src/. "${root}/share/k0s/kiosk/"
      cp -a kubeflex-src/. "${root}/share/k0s/kubeflex/"
      chmod 0755 "${root}"/share/k0s/kubeflex/*.sh
      if find sysext -name '*.pem' | grep -q .; then
        echo "ERROR: key material in a public sysext" >&2; exit 1
      fi
    - "%{sysext-pack}"
