kind: import
description: Install the NVIDIA Container Toolkit component systemd-sysupdate transfer definition.

sources:
  - kind: local
    path: files/os/sysupdate.nvidia-container-toolkit.d

config:
  target: /usr/lib/sysupdate.nvidia-container-toolkit.d
