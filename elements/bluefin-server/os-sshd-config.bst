kind: import
description: |
  Install a hardened sshd drop-in: key-based auth only, no direct root
  password login. Bring-up diagnostics use key-based access.

sources:
  - kind: local
    path: files/os/ssh/sshd_config.d

config:
  target: /etc/ssh/sshd_config.d
