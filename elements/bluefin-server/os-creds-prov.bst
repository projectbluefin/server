kind: import
description: Install first-boot systemd credentials provisioning helpers into target OS.

sources:
  - kind: local
    path: files/os/sysusers.d

config:
  target: /usr/lib/sysusers.d
