kind: import
description: Install sshd.service drop-ins for the live installer environment.

sources:
  - kind: local
    path: files/installer/sshd.service.d

config:
  target: /etc/systemd/system/sshd.service.d
