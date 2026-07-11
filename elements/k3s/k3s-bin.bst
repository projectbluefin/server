kind: manual
description: |
  Import the upstream k3s release binary.

  Pinned to the latest stable release for x86_64. The SHA256 is taken from
  the release's sha256sum-amd64.txt asset.

build-depends:
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

variables:
  # Do not try to strip the pre-built upstream binary; runtime-minimal
  # does not ship the stripper toolchain.
  strip-binaries: ""

sources:
  - kind: remote
    url: github:k3s-io/k3s/releases/download/v1.36.2%2Bk3s1/k3s
    ref: 65a55ec56c24eab44383086166ec620a491952b7e23941a49ddca6e8a4c4b4de

config:
  install-commands:
    - install -D -m 0755 k3s "%{install-root}/usr/bin/k3s"
