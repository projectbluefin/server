kind: import
description: |
  Install the udev rules from files/os/udev/rules.d: the USB installer's
  rule that forgets other disks' kernel partition devices before
  systemd-sysinstall runs (#359).

sources:
  - kind: local
    path: files/os/udev/rules.d

config:
  target: /usr/lib/udev/rules.d
