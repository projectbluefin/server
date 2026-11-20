kind: manual
description: |
  sshd configuration. The main sshd_config, which only includes
  /etc/ssh/sshd_config.d/*.conf, goes to the factory /etc. The vendor
  drop-in goes to /usr/lib/bluefin/sshd_config.d, and
  files/os/tmpfiles.d/50-bluefin-sshd.conf (os-resolv-conf.bst) links it into
  /etc/ssh/sshd_config.d: a disk install keeps /etc across A/B updates, so a
  copy would stay at the version the node first booted, while the link
  follows /usr. L leaves an operator's own file of that name alone.

build-depends:
  - base/base-stack.bst

sources:
  - kind: local
    path: files/os/ssh
    directory: ssh-src
  - kind: local
    path: files/os/sshd_config.d
    directory: dropin-src

variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -eu
      install -Dm0644 ssh-src/sshd_config "%{install-root}/etc/ssh/sshd_config"
      install -Dm0644 dropin-src/*.conf -t "%{install-root}/usr/lib/bluefin/sshd_config.d/"
