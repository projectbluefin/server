kind: manual
description: |
  Import upstream NetBird release binaries for the build architecture.

(@):
- include/arch.yml
- include/netbird.yml

build-depends:
- base/base-stack.bst

variables:
  strip-binaries: ""

sources:
- kind: tar
  url: github:netbirdio/netbird/releases/download/v%{netbird-version}/netbird_%{netbird-version}_linux_amd64.tar.gz
  ref: "%{netbird-x86-64-sha256}"
  directory: dist
  base-dir: ""

(?):
- arch == "aarch64":
    sources:
    - kind: tar
      url: github:netbirdio/netbird/releases/download/v%{netbird-version}/netbird_%{netbird-version}_linux_arm64.tar.gz
      ref: "%{netbird-arm64-sha256}"
      directory: dist
      base-dir: ""

config:
  install-commands:
  - |
    set -euo pipefail
    bindir="%{install-root}%{bindir}"

    mkdir -p "${bindir}"
    install -m 0755 dist/netbird "${bindir}/netbird"
