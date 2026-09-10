kind: import
description: Install passwordless wheel sudo policy for key-only operators.

sources:
  - kind: local
    path: files/os/sudoers.d

config:
  target: /etc/sudoers.d
