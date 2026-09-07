kind: manual
description: |
  Import the upstream k0s release binary.

  Pinned to the latest stable release for x86_64. The release tag comes from
  include/k0s.yml (%{k0s-upstream-tag}); only the SHA256 below is restated
  here, taken from that release's sha256sums.txt asset.

# %{k0s-upstream-tag} — the upstream release tag, URL-escaped. Single source
# of truth for the k0s version axis; see include/k0s.yml.
(@): include/k0s.yml

build-depends:
  # Base runtime providing /bin/sh and install in the sandbox.
  - base/base-stack.bst

variables:
  # Do not try to strip the pre-built upstream binary.
  strip-binaries: ""

sources:
  - kind: remote
    url: github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-amd64
    ref: ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f

config:
  install-commands:
    - |
      if [ "%{arch}" != "x86_64" ]; then
        echo "ERROR: elements/k0s/k0s-bin.bst pins the upstream k0s amd64 binary;" >&2
        echo "       arch=%{arch} has no pinned source. Add an arch-conditional" >&2
        echo "       source before building k0s for %{arch}." >&2
        exit 1
      fi
    - install -D -m 0755 k0s-%{k0s-upstream-tag}-amd64 "%{install-root}/usr/bin/k0s"
