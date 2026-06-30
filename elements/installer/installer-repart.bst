kind: import
description: |
  Installs the repart.d partition definitions into /usr/lib/repart.d/ inside
  the live installer environment. When the installer runs
  "systemd-repart --dry-run=no DEVICE", it reads these configs to know how
  to partition and populate the TARGET disk.

  Partition layout:
    10-esp.conf          EFI System Partition (vfat, 500M–1G)
    20-root-a.conf       Root slot A — DDI filesystem image copied here
    30-var.conf          /var — xfs, writable, grows to fill disk

sources:
  - kind: local
    path: files/installer/repart.d

config:
  target: /usr/lib/repart.d
