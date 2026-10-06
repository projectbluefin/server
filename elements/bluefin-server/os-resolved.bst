kind: import
description: |
  systemd-resolved defaults: multicast DNS on, so the node answers and
  resolves <hostname>.local on the links 20-wired.network enables it on
  (os-networkd.bst); LLMNR off. /usr/lib/systemd/resolved.conf.d, so A/B
  updates carry changes to installed nodes, whose /etc is kept.

sources:
  - kind: local
    path: files/os/resolved.conf.d

config:
  target: /usr/lib/systemd/resolved.conf.d
