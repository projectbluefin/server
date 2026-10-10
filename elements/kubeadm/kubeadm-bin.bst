kind: manual
description: |
  Upstream release binaries for a kubeadm worker node, each pinned by
  sha256 (published alongside the release asset): kubelet, kubeadm and
  kubectl from dl.k8s.io, crictl (cri-tools), the containerd static build
  (containerd, containerd-shim-runc-v2, ctr), the runc static build, and
  the full CNI reference plugin set. Versions come from include/kubeadm.yml;
  the amd64 or arm64 asset is picked by the build architecture.

  Layout: binaries in /usr/bin, CNI plugins in /usr/libexec/cni. Nothing
  goes under /opt: /opt/cni/bin stays a writable host directory that the
  cluster's CNI (Cilium) populates through a hostPath mount.

  No runtime `depends:`: oci/kubeadm-sysext.bst stages this artifact at a
  private location and ships exactly these files.

(@):
- include/arch.yml
- include/kubeadm.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/findutils.bst

variables:
  # Upstream release binaries: never strip or rewrite them.
  strip-binaries: ""

sources:
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubelet
  ref: 80f983da61642110456a95e13de3483895d65df6e18dcccfcee994d8947db026
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubeadm
  ref: b77649f3f9d4fc9cff73f9d2cc70c39ad2ca3ffddf5b43d33b2f3493a77aab9a
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubectl
  ref: 3cfeaf80be482b435b0aa214aff6e0b2c312ee23c0ff20810c75517b6004c6eb
  directory: k8s
- kind: tar
  url: github:kubernetes-sigs/cri-tools/releases/download/v%{crictl-version}/crictl-v%{crictl-version}-linux-amd64.tar.gz
  ref: 2e141e5b22cb189c40365a11807d69b76b9b3caced89fac2f4ec879408ce2177
  base-dir: ''
  directory: crictl
- kind: tar
  url: github:containerd/containerd/releases/download/v%{containerd-version}/containerd-static-%{containerd-version}-linux-amd64.tar.gz
  ref: d52dec99dd13e63c6a24f292936c15f929ad826be1ce39d7a77a3d840b1a2299
  base-dir: bin
  directory: containerd
- kind: remote
  url: github:opencontainers/runc/releases/download/v%{runc-version}/runc.amd64
  ref: 8781ab9f71c12f314d21c8e85f13ca1a82d90cf475aa5131a7b543fcc5487543
  directory: runc
- kind: tar
  url: github:containernetworking/plugins/releases/download/v%{cni-plugins-version}/cni-plugins-linux-amd64-v%{cni-plugins-version}.tgz
  ref: b275772da4026d2161bf8a8b41ed4786754c8a93ebfb6564006d5da7f23831e5
  base-dir: ''
  directory: cni

(?):
- arch == "aarch64":
    sources:
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubelet
      ref: 0d9b53143030a4e6655aa7540bb5e8a67a3afe5c011ef0cdf21aa8ef5906733d
      directory: k8s
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubeadm
      ref: 441e789c6c431869d63e597ca2c7357fc218822c65d8e127cb4f66f74181eb7f
      directory: k8s
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubectl
      ref: 39c98bca82875d9a9ddfb6f3c5ab17c3f78ea0801230683e538a67d5c053308d
      directory: k8s
    - kind: tar
      url: github:kubernetes-sigs/cri-tools/releases/download/v%{crictl-version}/crictl-v%{crictl-version}-linux-arm64.tar.gz
      ref: 519071de89b64c43e2a1661bb5489c6c3fd5e9e5fcef75e50e542b0c891f1118
      base-dir: ''
      directory: crictl
    - kind: tar
      url: github:containerd/containerd/releases/download/v%{containerd-version}/containerd-static-%{containerd-version}-linux-arm64.tar.gz
      ref: f0e77d2bd29c6a4a463c593b3e9e39ce31b830ff572aba98ea544aa3b8f08be7
      base-dir: bin
      directory: containerd
    - kind: remote
      url: github:opencontainers/runc/releases/download/v%{runc-version}/runc.arm64
      ref: 3c9a8e9e6dafd00db61f4611692447ebab4a56388bae4f82192aed67b66df712
      directory: runc
    - kind: tar
      url: github:containernetworking/plugins/releases/download/v%{cni-plugins-version}/cni-plugins-linux-arm64-v%{cni-plugins-version}.tgz
      ref: 16484966a46b4692028ba32d16afd994e079dc2cc63fbc2191d7bfaf5e11f3dd
      base-dir: ''
      directory: cni

config:
  install-commands:
  - |
    set -eu
    bin="%{install-root}%{bindir}"
    install -d "${bin}"
    for b in kubelet kubeadm kubectl; do install -m 0755 "k8s/${b}" "${bin}/"; done
    install -m 0755 crictl/crictl "${bin}/"
    for b in containerd containerd-shim-runc-v2 ctr; do install -m 0755 "containerd/${b}" "${bin}/"; done
    install -m 0755 "runc/runc.%{go-arch}" "${bin}/runc"
    install -d "%{install-root}%{libexecdir}/cni"
    find cni -maxdepth 1 -type f -perm -u+x -exec install -m 0755 -t "%{install-root}%{libexecdir}/cni" {} +
    for p in loopback bridge host-local portmap; do
      [ -x "%{install-root}%{libexecdir}/cni/${p}" ] || { echo "ERROR: CNI plugin ${p} missing" >&2; exit 1; }
    done
