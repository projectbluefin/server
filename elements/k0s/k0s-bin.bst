kind: manual
description: |
  Import the upstream k0s release binary for the build architecture.

  The release tag comes from include/k0s.yml (%{k0s-upstream-tag}); only the
  SHA256 of each architecture's binary is restated here, taken from that
  release's sha256sums.txt asset.

# %{k0s-upstream-tag} — the upstream release tag, URL-escaped. Single source
# of truth for the k0s version axis; see include/k0s.yml.
(@):
  - include/arch.yml
  - include/k0s.yml

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

(?):
  - arch == "aarch64":
      sources:
        - kind: remote
          url: github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-arm64
          ref: 6301f64d98f9e4f6fbc2892bc66d137bb4ad5840685300772d8391614d47b8aa

config:
  install-commands:
    - install -D -m 0755 k0s-%{k0s-upstream-tag}-%{go-arch} "%{install-root}/usr/bin/k0s"
