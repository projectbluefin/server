kind: import
description: Install persistent core operator home directory definitions.

sources:
  - kind: local
    path: files/os/tmpfiles.d

config:
  target: /usr/lib/tmpfiles.d
