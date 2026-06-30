kind: import
description: |
  Installs installer.target and installer.service into /usr/lib/systemd/system/
  inside the live installer environment. These units orchestrate the install
  sequence: network-online -> sysupdate (pull DDI) -> installer script -> poweroff.

sources:
  - kind: local
    path: files/installer/units

config:
  target: /usr/lib/systemd/system
