kind: import
description: Install systemd-sysupdate post-update hook for Kured coordination.

sources:
  - kind: local
    path: files/os/systemd/systemd-sysupdate.service.d

config:
  target: /usr/lib/systemd/system/systemd-sysupdate.service.d
