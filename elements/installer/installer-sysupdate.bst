kind: import
description: |
  Installs the sysupdate.d transfer config into /usr/lib/sysupdate.d/ inside
  the live installer environment. The installer service calls:
    systemd-sysupdate --definitions=/usr/lib/sysupdate.d update
  to pull the OS DDI from GitHub Releases before running systemd-repart.

sources:
  - kind: local
    path: files/installer/sysupdate.d

config:
  target: /usr/lib/sysupdate.d
