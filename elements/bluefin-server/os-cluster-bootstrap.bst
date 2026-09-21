kind: manual
description: |
  Install the host units that bring up the Kubernetes control plane and seed
  the cluster, plus the configuration they read.

  Units: kubelet.service (+ the kubeadm drop-in), kubeadm-init.service,
  bluefin-cluster-repo.service and bluefin-cluster-bootstrap.service, together
  with the systemd-sysext.service drop-in that reloads systemd after a merge so
  sysext-delivered units become visible.

  Also stages /usr/share/bluefin/kubeadm.yaml and the
  /usr/libexec/bluefin-cluster-repo helper.

build-depends:
  - base/base-stack.bst

sources:
  - kind: local
    path: files/os/systemd/system
    directory: units-src
  - kind: local
    path: files/os/systemd/systemd-sysext.service.d
    directory: sysext-dropin-src
  - kind: local
    path: files/kubernetes/kubeadm.yaml
    directory: kubeadm-src
  - kind: local
    path: files/os/libexec
    directory: libexec-src
  - kind: local
    path: files/kubernetes/sysctl.d
    directory: sysctl-src

# This element stages systemd units, a YAML config and a shell helper. FSDK's
# default strip-commands shell out to freedesktop-sdk-stripper, which
# base/base-stack.bst does not provide, so the default turns a no-op into
# `command not found` (exit 127). Same contract as os-countme.bst,
# os-image-info.bst and os-release-flatcar.bst.
variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"

      mkdir -p "${OUT}/usr/lib/systemd/system"
      cp -a units-src/. "${OUT}/usr/lib/systemd/system/"

      mkdir -p "${OUT}/usr/lib/systemd/system/systemd-sysext.service.d"
      cp -a sysext-dropin-src/. "${OUT}/usr/lib/systemd/system/systemd-sysext.service.d/"

      mkdir -p "${OUT}/usr/lib/sysctl.d"
      cp -a sysctl-src/. "${OUT}/usr/lib/sysctl.d/"

      mkdir -p "${OUT}/usr/share/bluefin"
      cp -a kubeadm-src/kubeadm.yaml "${OUT}/usr/share/bluefin/kubeadm.yaml"
      chmod 0644 "${OUT}/usr/share/bluefin/kubeadm.yaml"

      mkdir -p "${OUT}/usr/libexec"
      cp -a libexec-src/bluefin-cluster-repo "${OUT}/usr/libexec/bluefin-cluster-repo"
      chmod 0755 "${OUT}/usr/libexec/bluefin-cluster-repo"
