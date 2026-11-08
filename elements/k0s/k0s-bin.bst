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
    ref: 60bac39d4ed8292adb8576a55866389cde4700f9be7d152587e15f8aa67c12fc

(?):
  - arch == "aarch64":
      sources:
        - kind: remote
          url: github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-arm64
          ref: cf4763c6c0e08b9c53b3c3ecd7f35f7bee50aff2a2347fa5a8cc4c47ab489b2f

config:
  install-commands:
    - install -D -m 0755 k0s-%{k0s-upstream-tag}-%{go-arch} "%{install-root}/usr/bin/k0s"
