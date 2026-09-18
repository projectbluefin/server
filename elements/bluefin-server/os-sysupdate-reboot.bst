kind: import
description: Configure reboot coordination drop-in for systemd-sysupdate-reboot.

sources:
  - kind: local
    path: files/os/systemd/systemd-sysupdate-reboot.service.d

config:
  target: /usr/lib/systemd/system/systemd-sysupdate-reboot.service.d
