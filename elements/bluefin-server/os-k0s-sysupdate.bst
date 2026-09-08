kind: import
description: Install the k0s component systemd-sysupdate transfer definition.

sources:
  - kind: local
    path: files/os/sysupdate.k0s.d

config:
  target: /usr/lib/sysupdate.k0s.d
