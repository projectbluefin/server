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
    ref: 18c304d53cdd70095e99c6b859b269b4fef0bb84579d7e7185271a9135694a31

(?):
  - arch == "aarch64":
      sources:
        - kind: remote
          url: github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-arm64
          ref: 04f685c8c9c29262da64acf26fd928452f19d449ac58729592f686f915882319

config:
  install-commands:
    - install -D -m 0755 k0s-%{k0s-upstream-tag}-%{go-arch} "%{install-root}/usr/bin/k0s"
