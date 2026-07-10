kind: import
description: Install systemd-sysupdate transfer definitions into target OS image.

sources:
  - kind: local
    path: files/os/sysupdate.d

config:
  target: /usr/lib/sysupdate.d
