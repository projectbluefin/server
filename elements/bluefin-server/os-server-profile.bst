kind: manual
description: |
  Native Complete/Core profile consumer. Only a small host staging launcher
  lives in Core; Kubernetes, containerd, Console and the root helper live in
  the verified opt-in Server extension.
  The shared OS unit import already owns bluefin-server-profile.service;
  this element installs only its launcher and explicit activation link.

build-depends:
- base/base-stack.bst

sources:
- kind: local
  path: files/os/libexec/bluefin-server-profile

variables:
  strip-binaries: ""

config:
  install-commands:
  - install -Dm0755 bluefin-server-profile '%{install-root}/usr/libexec/bluefin-server-profile'
  - mkdir -p '%{install-root}/usr/lib/systemd/system/multi-user.target.wants'
  - ln -s ../bluefin-server-profile.service '%{install-root}/usr/lib/systemd/system/multi-user.target.wants/bluefin-server-profile.service'
