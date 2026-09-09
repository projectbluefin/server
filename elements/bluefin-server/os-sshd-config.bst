kind: import
description: Install sshd configuration and drop-ins.

sources:
  - kind: local
    path: files/os/ssh

config:
  target: /etc/ssh
