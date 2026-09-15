kind: import
description: |
  Installs the repart.d partition definitions into /usr/lib/repart.d/ inside
  the live installer environment. When the installer runs
  "systemd-repart --dry-run=no DEVICE", it reads these configs to know how
  to partition and populate the TARGET disk.

  Partition layout:
    10-esp.conf          EFI-SYSTEM (vfat, 500M–1G)
    20-usr-a.conf        USR-A — DDI /usr payload copied here block-for-block
    30-usr-b.conf        USR-B — empty A/B rollback slot
    40-oem.conf          OEM — ext4, filesystem label OEM (stage 2 boot dep)
    50-root.conf         ROOT — writable state, grows to fill the disk

sources:
  - kind: local
    path: files/installer/repart.d

config:
  target: /usr/lib/repart.d
