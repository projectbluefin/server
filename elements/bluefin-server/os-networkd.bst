kind: import
description: Install wired DHCP configuration for the target OS.

sources:
  - kind: local
    path: files/os/systemd/network

config:
  target: /usr/lib/systemd/network
