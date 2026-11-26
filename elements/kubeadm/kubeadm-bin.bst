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
  ref: 17f0007724a6c3b1866a66483dd4e8f7e60199601ff346c7b0ce3923d1aaf4a2
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubeadm
  ref: 7071b814f9badee75b99482fbd75e6c79aa06a9a3013339660337a490eb4b98e
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubectl
  ref: eeddea383a302f9a633a292af1d886054c7cf152fb407f827f12bfe286dc46d6
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
  ref: 3c8d24628a006cf52d8791cf8c4586f3a0cb7e29bed8ae4264aca3cb1edb972d
  directory: runc
- kind: tar
  url: github:containernetworking/plugins/releases/download/v%{cni-plugins-version}/cni-plugins-linux-amd64-v%{cni-plugins-version}.tgz
  ref: b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303
  base-dir: ''
  directory: cni

(?):
- arch == "aarch64":
    sources:
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubelet
      ref: 542f14c7ffcf10a149dba1e1b3b40ca8b3774c8016025aa55a89ba9868bc1710
      directory: k8s
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubeadm
      ref: 8fc928f51a4433fda7d9e6e49e35efd3cf1dfd1777620590a30e99c5bd2657e1
      directory: k8s
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubectl
      ref: e69973a0b8c23412f2f6bba6a91b98579a1787c4d731fb4cb5987ba273763318
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
      ref: 9edac6cba77b34d955bcdbf7001a1193f8964b255f0a7cf06ced3adf11f7cc00
      directory: runc
    - kind: tar
      url: github:containernetworking/plugins/releases/download/v%{cni-plugins-version}/cni-plugins-linux-arm64-v%{cni-plugins-version}.tgz
      ref: 56171987d3947707c3563db2f4001bccaf50fd63468611b9f3cbecb1375ee7ec
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
