kind: import
description: |
  Install the tmpfiles.d rule that creates /etc/resolv.conf as a symlink to
  systemd-resolved's resolv.conf. FSDK 26.08 ships no /etc/resolv.conf rule
  (upstream systemd leaves the symlink to the distro), and this DDI boots
  with an empty /etc, so nothing ever creates the symlink and kubelet fails
  every pod sandbox with "open /etc/resolv.conf: no such file or directory".
  The other files/os/tmpfiles.d rules land here too (iSCSI, motd, and the
  /etc/profile.d link to the bash prompt from os-prompt.bst).

sources:
  - kind: local
    path: files/os/tmpfiles.d

config:
  target: /usr/lib/tmpfiles.d
