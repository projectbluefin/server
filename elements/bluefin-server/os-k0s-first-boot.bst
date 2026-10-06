kind: import
description: |
  Install the systemd units from files/os/systemd/system: the first-boot k0s
  sysext activation units, first-start SSH host key generation
  (ssh-host-keygen.service plus its sshd.service and systemd-ssh-generator
  sshd-generated@.service drop-ins), the installer
  source ESP mounts (run-bluefin-boot.mount for netboot,
  run-bluefin-installer.mount for the USB installer), and the
  systemd-sysinstall.service drop-in the USB installer boots into, the update
  units (systemd-sysupdate(-reboot) drop-ins for diskless conditions, the
  systemd-sysupdated drop-in masking the UKI transfer on diskless boots, the
  kured flag, the reboot interlock: operator lock files, failed-update guard,
  Kubernetes; the boot deadline; the diskless update check;
  bluefin-update-status.service for the login banners and
  bluefin-update-status-migrate.service, which enables it on nodes that
  updated from an image without it).

sources:
  - kind: local
    path: files/os/systemd/system

config:
  target: /usr/lib/systemd/system
