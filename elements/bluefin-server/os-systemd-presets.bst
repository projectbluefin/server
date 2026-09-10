kind: import
description: |
  Install the systemd system presets that enable networkd, the k0s first-boot
  activation unit, and the persistent /var mount on the installed OS.

sources:
  - kind: local
    path: files/os/systemd/system-preset

config:
  target: /usr/lib/systemd/system-preset
