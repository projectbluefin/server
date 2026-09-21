kind: manual
description: |
  Import the upstream containernetworking/plugins CNI binaries.

  The linux/amd64 release tarball for the tag named by include/kubernetes.yml
  (%{cni-upstream-tag}); only the SHA256 below is restated here, taken from
  that release's sha256 asset.

  Each plugin is installed by name rather than by wildcard, so an upstream
  rename or removal fails the build instead of silently shipping a CNI set
  that no longer matches what Cilium and the kubelet expect.

# %{cni-upstream-tag} — the upstream CNI plugins release tag. Single source of
# truth for the Kubernetes version axis; see include/kubernetes.yml.
(@): include/kubernetes.yml

build-depends:
  # Base runtime providing /bin/sh and install in the sandbox.
  - base/base-stack.bst

variables:
  # Do not try to strip the pre-built upstream binaries.
  strip-binaries: ""

sources:
  - kind: tar
    url: github:containernetworking/plugins/releases/download/%{cni-upstream-tag}/cni-plugins-linux-amd64-%{cni-upstream-tag}.tgz
    ref: b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303
    base-dir: ""
    directory: cni-src

config:
  install-commands:
    - |
      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/kubernetes/cni-plugins.bst pins the upstream" >&2
        echo "       linux/amd64 CNI plugins tarball; arch=%{arch} has no" >&2
        echo "       pinned source. Add an arch-conditional source before" >&2
        echo "       building the CNI plugins for %{arch}." >&2
        exit 1
      fi
    - install -D -m 0755 cni-src/bandwidth "%{install-root}/usr/local/bin/cni/bandwidth"
    - install -D -m 0755 cni-src/bridge "%{install-root}/usr/local/bin/cni/bridge"
    - install -D -m 0755 cni-src/dhcp "%{install-root}/usr/local/bin/cni/dhcp"
    - install -D -m 0755 cni-src/dummy "%{install-root}/usr/local/bin/cni/dummy"
    - install -D -m 0755 cni-src/firewall "%{install-root}/usr/local/bin/cni/firewall"
    - install -D -m 0755 cni-src/host-device "%{install-root}/usr/local/bin/cni/host-device"
    - install -D -m 0755 cni-src/host-local "%{install-root}/usr/local/bin/cni/host-local"
    - install -D -m 0755 cni-src/ipvlan "%{install-root}/usr/local/bin/cni/ipvlan"
    - install -D -m 0755 cni-src/loopback "%{install-root}/usr/local/bin/cni/loopback"
    - install -D -m 0755 cni-src/macvlan "%{install-root}/usr/local/bin/cni/macvlan"
    - install -D -m 0755 cni-src/portmap "%{install-root}/usr/local/bin/cni/portmap"
    - install -D -m 0755 cni-src/ptp "%{install-root}/usr/local/bin/cni/ptp"
    - install -D -m 0755 cni-src/sbr "%{install-root}/usr/local/bin/cni/sbr"
    - install -D -m 0755 cni-src/static "%{install-root}/usr/local/bin/cni/static"
    - install -D -m 0755 cni-src/tap "%{install-root}/usr/local/bin/cni/tap"
    - install -D -m 0755 cni-src/tuning "%{install-root}/usr/local/bin/cni/tuning"
    - install -D -m 0755 cni-src/vlan "%{install-root}/usr/local/bin/cni/vlan"
    - install -D -m 0755 cni-src/vrf "%{install-root}/usr/local/bin/cni/vrf"
