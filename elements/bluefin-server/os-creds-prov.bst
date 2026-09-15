kind: manual

description: |
  Install first-boot systemd credential provisioning contracts into the target OS.
  Supports sysusers credentials, tmpfiles.extra payloads for SSH keys and local
  files, systemd-network-generator network.* credentials, and a non-interactive
  systemd-firstboot credential gate.

build-depends:
  - base/base-stack.bst

sources:
  - kind: local
    path: files/os/sysusers.d
    directory: sysusers-src
  - kind: local
    path: files/os/creds/tmpfiles.d
    directory: tmpfiles-src
  - kind: local
    path: files/os/creds/systemd/system
    directory: systemd-src

config:
  install-commands:
    - |
      set -euo pipefail

      install -Dm0644 sysusers-src/*.conf -t "%{install-root}/usr/lib/sysusers.d/"
      install -Dm0644 tmpfiles-src/*.conf -t "%{install-root}/usr/lib/tmpfiles.d/"
      mkdir -p "%{install-root}/usr/lib/systemd/system"
      cp -a systemd-src/. "%{install-root}/usr/lib/systemd/system/"
