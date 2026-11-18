kind: import
description: |
  Install systemd presets ensuring sshd is present but off by default and the
  systemd-sysupdate feature migration is enabled.

sources:
  - kind: local
    path: files/os/systemd/system-preset

config:
  target: /usr/lib/systemd/system-preset
