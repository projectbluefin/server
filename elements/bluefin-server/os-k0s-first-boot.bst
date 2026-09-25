kind: import
description: |
  Install the systemd units from files/os/systemd/system: the first-boot k0s
  sysext activation units, var.mount, and first-start SSH host key generation
  (ssh-host-keygen.service plus its sshd.service drop-in).

sources:
  - kind: local
    path: files/os/systemd/system

config:
  target: /usr/lib/systemd/system
