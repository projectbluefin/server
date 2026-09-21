kind: manual
description: |
  Produce a systemd-sysext extension image for upstream Kubernetes.

  Output: kubernetes-<k8s-version>.raw, kubernetes-<k8s-version>.raw.zst, and
  SHA256SUMS. Contains /usr/bin/{kubectl,kubeadm,kubelet}, the CNI plugins
  under /usr/local/bin/cni/, the two version stamp files the upstream recipe
  publishes, and the extension-release metadata.

  This is a re-bake of the flatcar/sysext-bakery `kubernetes.sysext` recipe
  under BuildStream, so release signing and provenance stay in-repo. The
  layout is deliberately wire-compatible with extensions.flatcar.org: an
  operator can repoint the sysupdate source at upstream without changing
  anything else.

  No certificate or key material is generated or shipped. Cluster TLS is
  issued at runtime — kubelet client certs by kubeadm's TLS bootstrap,
  kubelet serving certs by kubelet-csr-approver, everything else by
  cert-manager. Nothing here is a manifest either; the seed and Argo-owned
  trees are staged by elements/bluefin-server/os-cluster-manifests.bst.

(@):
  - include/arch.yml
  - include/kubernetes.yml

build-depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/erofs-utils.bst
  - freedesktop-sdk.bst:components/xz.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - filename: kubernetes/kubernetes-bin.bst
    config:
      location: /
  - filename: kubernetes/cni-plugins.bst
    config:
      location: /

sources:
  - kind: local
    path: files/kubernetes/sysext
    directory: sysext-src

variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      OUT="%{install-root}"
      FNAME="kubernetes-%{k8s-version}.raw"

      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/oci/kubernetes-sysext.bst only supports x86_64 (got %{arch})" >&2
        exit 1
      fi

      mkdir -p sysext/usr/bin
      mkdir -p sysext/usr/local/bin/cni
      mkdir -p sysext/usr/local/share
      mkdir -p sysext/usr/lib/extension-release.d
      mkdir -p "${OUT}"

      # Stage the Kubernetes node binaries.
      cp -a /usr/bin/kubectl sysext/usr/bin/kubectl
      cp -a /usr/bin/kubeadm sysext/usr/bin/kubeadm
      cp -a /usr/bin/kubelet sysext/usr/bin/kubelet
      chmod 0755 sysext/usr/bin/kubectl
      chmod 0755 sysext/usr/bin/kubeadm
      chmod 0755 sysext/usr/bin/kubelet

      # Stage the CNI plugins where the upstream recipe publishes them.
      cp -a /usr/local/bin/cni/. sysext/usr/local/bin/cni/

      # Stage the version stamps the upstream recipe publishes, so an
      # operator can read the delivered versions off a merged /usr.
      echo "%{k8s-version}" > sysext/usr/local/share/kubernetes-version
      echo "%{cni-version}" > sysext/usr/local/share/kubernetes-cni-version

      # Stage extension release metadata
      cp -a sysext-src/extension-release.kubernetes sysext/usr/lib/extension-release.d/
      echo "VERSION_ID=%{k8s-version}" >> sysext/usr/lib/extension-release.d/extension-release.kubernetes
      echo "ARCHITECTURE=%{systemd-arch}" >> sysext/usr/lib/extension-release.d/extension-release.kubernetes

      # Build EROFS image
      mkfs.erofs -d0 "${OUT}/${FNAME}" sysext

      # Compress release asset
      zstd -T0 -19 -q "${OUT}/${FNAME}" -o "${OUT}/${FNAME}.zst"

      (
        cd "${OUT}"
        sha256sum --binary "${FNAME}.zst" > SHA256SUMS
      )
