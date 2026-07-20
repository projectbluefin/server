kind: import
description: |
  Install a temporary sshd drop-in that allows root login for bring-up
  and cluster boot tests.

sources:
  - kind: local
    path: files/os/ssh/sshd_config.d

config:
  target: /etc/ssh/sshd_config.d
