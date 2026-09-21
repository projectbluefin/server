kind: manual
description: |
  Import the upstream Kubernetes node binaries.

  kubectl, kubeadm and kubelet for x86_64, pinned to the release named by
  include/kubernetes.yml (%{k8s-upstream-tag}); only the SHA256 of each
  binary is restated here, taken from the `.sha256` asset published beside it
  on dl.k8s.io.

# %{k8s-upstream-tag} — the upstream Kubernetes release directory on
# dl.k8s.io. Single source of truth for the Kubernetes version axis; see
# include/kubernetes.yml.
(@): include/kubernetes.yml

build-depends:
  # Base runtime providing /bin/sh and install in the sandbox.
  - base/base-stack.bst

variables:
  # Do not try to strip the pre-built upstream binaries.
  strip-binaries: ""

sources:
  - kind: remote
    url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubectl
    ref: 8b8f088da2dab964f853b38464033b1be15ede2839eca751482357c45abdd05a
  - kind: remote
    url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubeadm
    ref: 10d054585907f2c8bb823c84f6a66b3bd2a474c3d795475f04e9a44f78650fe6
  - kind: remote
    url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubelet
    ref: cf2562db46c48ab84cc3791540778ee7fb1a0a008529adbb434723dd02ed8b4b

config:
  install-commands:
    - |
      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/kubernetes/kubernetes-bin.bst pins the upstream" >&2
        echo "       linux/amd64 Kubernetes binaries; arch=%{arch} has no pinned" >&2
        echo "       source. Add an arch-conditional source before building" >&2
        echo "       Kubernetes for %{arch}." >&2
        exit 1
      fi
    - install -D -m 0755 kubectl "%{install-root}/usr/bin/kubectl"
    - install -D -m 0755 kubeadm "%{install-root}/usr/bin/kubeadm"
    - install -D -m 0755 kubelet "%{install-root}/usr/bin/kubelet"
