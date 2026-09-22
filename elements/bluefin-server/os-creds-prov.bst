kind: import
description: Install the static root and core account definitions into target OS.

sources:
  - kind: local
    path: files/os/sysusers.d

config:
  target: /usr/lib/sysusers.d
