kind: import
description: Install the Kubernetes component systemd-sysupdate transfer definition.

sources:
  - kind: local
    path: files/os/sysupdate.kubernetes.d

config:
  target: /usr/lib/sysupdate.kubernetes.d
