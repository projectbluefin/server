kind: import
description: Install the first-boot k0s sysext activation unit.

sources:
  - kind: local
    path: files/os/systemd/system

config:
  target: /usr/lib/systemd/system
