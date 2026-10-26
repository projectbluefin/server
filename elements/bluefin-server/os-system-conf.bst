kind: import
description: |
  Service manager defaults: the runtime hardware watchdog, so a node that
  freezes (kernel or PID 1) resets itself. /usr/lib/systemd/system.conf.d,
  so A/B updates carry changes to installed nodes, whose /etc is kept.

sources:
  - kind: local
    path: files/os/system.conf.d

config:
  target: /usr/lib/systemd/system.conf.d
