kind: import
description: |
  Install the systemd-sysupdate deprecated-feature migration helper so a
  feature the release no longer ships cannot silently stop the next update.

  The executable lands in /usr/bin; the boot-time unit, the preset that
  enables it, and the ExecStartPre drop-in on systemd-sysupdate.service are
  shipped next to the other system units.

sources:
  - kind: local
    path: files/os/sysupdate-migrate

config:
  target: /usr/bin
