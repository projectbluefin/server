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
  ref: 25d2645e4f8975dec8d864b7cf289e9609456fc864c892c9c6e644c384a2a061
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubeadm
  ref: ea583f31809d73394f4b038c6b3c5f9fecdb5627a82e203edae1d0e742e71504
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{kubernetes-version}/bin/linux/amd64/kubectl
  ref: c49a28f1f4efc4d475ed05f47f2ce8e563bf7bef69ed77fe1b924ea6d83b6327
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
  ref: 3f3921dbbee7723e9868f97e88e51ffc910206e3ba55646e74d93d24ea76023c
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
      ref: 322cf11cd6b5d217e1e9f309b9fd119a3ec60cfcecf1d2c4e284f0d0762f9151
      directory: k8s
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubeadm
      ref: d0d813b1a1b256a266e1bd6d2122f286ea682f62c850dc4fee13197f89bc36de
      directory: k8s
    - kind: remote
      url: k8s_dl:release/v%{kubernetes-version}/bin/linux/arm64/kubectl
      ref: 283f1be6a46b3695b625e25030106b8ffe18bd0d3a900f5b65c259ca407f04f5
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
      ref: 6be27a061ef89bb14c6cb495405bba80f46cea213b8f79378a6086b1bac6b747
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
