kind: manual
description: |
  Opt-in systemd-sysext with the Bluefin Server homelab component set:
  vendored, pinned Kubernetes manifests (rendered offline from pinned
  upstream charts by scripts/render-homelab-manifests.py, images pinned by
  digest) under /usr/share/bluefin/homelab/, and bluefin-homelab-apply.service,
  which applies the components /etc/bluefin/homelab.conf enables to the
  node's kubeadm or k0s control plane. kubelet.service and
  k0scontroller.service want the unit; it does nothing without homelab.conf.

  Multi-node (HOMELAB_ROLE in homelab.conf): bluefin-cluster from
  homelab/bluefin-cluster.bst with its units (prepare and serve on the
  control plane, join on a node; see files/homelab/cluster/README.md); the
  base OS turns on mDNS (os-networkd.bst, os-resolved.bst). Every unit is a
  no-op without homelab.conf and outside its role.

  Output: homelab_<image-version>.raw, .raw.zst, and SHA256SUMS. Locked to
  one image version like the KubeStellar sysext and updated in lock-step
  with the OS through the `homelab` sysupdate feature.

(@):
- include/arch.yml
- include/image.yml
- include/sysext.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/zstd.bst
- filename: homelab/bluefin-cluster.bst
  config:
    location: /bluefin-cluster

sources:
- kind: local
  path: files/homelab/sysext
  directory: sysext-src
- kind: local
  path: files/homelab/manifests
  directory: manifests-src

variables:
  strip-binaries: ""
  sysext-name: "homelab"
  sysext-image: "homelab_%{image-version}"
  sysext-release: "homelab_%{image-version}"
  sysext-version: "%{image-version}"
  # bluefin-cluster is a native binary.
  sysext-architecture: "%{systemd-arch}"

config:
  install-commands:
  - |
    set -euo pipefail
    src=sysext-src
    unitdir="sysext%{indep-libdir}/systemd/system"
    share="sysext%{datadir}/bluefin/homelab"

    install -D -m 0755 "${src}/bluefin-homelab-apply" "sysext%{libexecdir}/bluefin-homelab-apply"
    install -D -m 0644 -t "${unitdir}" "${src}/bluefin-homelab-apply.service"
    for wants in kubelet.service.wants k0scontroller.service.wants; do
      mkdir -p "${unitdir}/${wants}"
      ln -s ../bluefin-homelab-apply.service "${unitdir}/${wants}/bluefin-homelab-apply.service"
    done
    install -D -m 0644 -t "${unitdir}" "${src}/bluefin-cluster-prepare.service" \
      "${src}/bluefin-cluster-serve.service" "${src}/bluefin-cluster-join.service" \
      "${src}/bluefin-cluster-hosts.service" \
      "${src}/bluefin-cluster-hosts.timer"
    cp -a /bluefin-cluster%{prefix}/. sysext%{prefix}/
    for link in kubeadm-init.service.wants/bluefin-cluster-prepare.service \
        k0scontroller.service.wants/bluefin-cluster-prepare.service \
        kubelet.service.wants/bluefin-cluster-serve.service \
        k0scontroller.service.wants/bluefin-cluster-serve.service \
        multi-user.target.wants/bluefin-cluster-join.service \
        multi-user.target.wants/bluefin-cluster-hosts.timer; do
      mkdir -p "${unitdir}/${link%/*}"
      ln -s "../${link#*/}" "${unitdir}/${link}"
    done
    mkdir -p "${share}"
    cp -a manifests-src/. "${share}/"
    install -m 0644 "${src}/homelab.conf.example" "${share}/homelab.conf.example"

    # Every registry reference carries a digest (bare names are the GPU
    # Operator's repository/image/version triples, pinned by version).
    if grep -rnE '^[[:space:]-]*image: "?[^[:space:]]*[/:]' "${share}" | grep -v '@sha256:[0-9a-f]\{64\}'; then
      echo "ERROR: image reference not pinned by digest" >&2; exit 1
    fi
    if find sysext -name '*.pem' -o -name '*.key' -o -name '*.dnssd' -o -name 'passphrase' | grep -q .; then
      echo "ERROR: key material in a public sysext" >&2; exit 1
    fi

  - "%{sysext-pack}"
