kind: manual
description: |
  Opt-in systemd-sysext with the NetBird VPN daemon and CLI tool.

(@):
- include/arch.yml
- include/image.yml
- include/netbird.yml
- include/sysext.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/zstd.bst
- filename: runtimes/netbird-bin.bst
  config:
    location: /runtime

sources:
- kind: local
  path: files/netbird/sysext
  directory: sysext-src

variables:
  strip-binaries: ""
  sysext-name: "netbird"
  sysext-image: "netbird_%{image-version}"
  sysext-release: "netbird_%{image-version}"
  sysext-version: "%{image-version}"
  sysext-architecture: "%{systemd-arch}"

config:
  install-commands:
  - |
    set -euo pipefail
    mkdir -p sysext%{bindir} \
             sysext%{indep-libdir}/systemd/system \
             sysext%{indep-libdir}/systemd/system-preset

    install -m0755 /runtime%{bindir}/netbird sysext%{bindir}/netbird
    install -m0644 sysext-src/netbird.service sysext%{indep-libdir}/systemd/system/netbird.service
    install -m0644 sysext-src/80-netbird.preset sysext%{indep-libdir}/systemd/system-preset/80-netbird.preset
  - "%{sysext-pack}"
