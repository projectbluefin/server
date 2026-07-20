kind: import
description: |
  Install a systemd preset that enables sshd.service on first boot.

  This is a temporary bring-up aid; see docs/skills/factory-integration.md
  for the removal plan.

sources:
  - kind: local
    path: files/os/systemd/system-preset

config:
  target: /usr/lib/systemd/system-preset
