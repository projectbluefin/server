kind: import
description: |
  The interactive bash prompt, user@host:cwd$ with a blue @, in
  /usr/lib/bluefin/profile.d; files/os/tmpfiles.d/50-bluefin-prompt.conf
  (os-resolv-conf.bst) links it into /etc/profile.d.

sources:
  - kind: local
    path: files/os/profile.d

config:
  target: /usr/lib/bluefin/profile.d
