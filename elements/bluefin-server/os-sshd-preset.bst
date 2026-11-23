kind: import
description: |
  Install systemd presets ensuring sshd is present but off by default, and
  enabling the daily countme timer (80-bluefin-countme.preset).

sources:
  - kind: local
    path: files/os/systemd/system-preset

config:
  target: /usr/lib/systemd/system-preset
