kind: import
description: |
  Update helpers in /usr/libexec (units in files/os/systemd/system, enabled by
  80-bluefin-updates.preset):
  - bluefin-diskless-update-check, run by bluefin-diskless-update-check.timer
    on diskless boots only: fetches the signed SHA256SUMS from the directory
    the node booted from, and when it lists a newer bluefin-server_<ver>.raw
    than the running IMAGE_VERSION and the boot origin is not pinned to a
    versioned file, touches /run/reboot-required for kured or the operator.
    It never reboots.
  - bluefin-boot-deadline, run by bluefin-boot-deadline.timer on boot-counted
    boots only: reboots (or flags kured on a Kubernetes node) when the boot has
    not reached boot-complete.target by the deadline, so systemd-boot falls
    back to the previous UKI.
  - bluefin-update-pending: `systemd-sysupdate pending`, minus a version whose
    UKI already used up its boot tries; gates the kured flag and the nightly
    reboot so a rolled-back node does not reboot into it again.
  - bluefin-reboot-lock: FleetLock client (curl). `acquire` gates the nightly
    reboot and the boot deadline's reboot on a reboot slot from the server in
    /etc/bluefin/reboot-lock.conf or the bluefin.reboot-lock.* credentials;
    `release`, run by bluefin-reboot-lock-release.service (enabled in /usr by
    elements/oci/bluefin-server-usr.bst) after a good boot, gives it back.
    Both do nothing without a server.
  - bluefin-update-status, run by bluefin-update-status.service at boot and
    after every systemd-sysupdate.service run: records the last successful
    check and the last error in /var/lib/bluefin-update-status and writes the
    version, update state and any error to /run/issue.d (console) and
    /run/motd (login and SSH, through the /etc/motd link in
    40-bluefin-motd.conf).
  - bluefin-update-status-migrate, run once per installed node by
    bluefin-update-status-migrate.service (enabled in /usr by
    elements/oci/bluefin-server-usr.bst): presets apply on first boot only,
    so a node that updated from an image without bluefin-update-status.service
    never enables it; this enables and starts it when it is not enabled yet.
  - bluefin-sysext-fetch, run by the opt-in bluefin-sysext-fetch.service
    (disabled by 80-bluefin-opt-in.preset; the homelab Ignition templates
    link it): once per image version, installs the version-locked sysexts of
    the sysupdate features the node enabled, from the USB installer's seed
    on the ESP, the boot server (diskless) or the release
    (systemd-sysupdate), and merges them.
  Runtime tools: bash, coreutils, curl, gpgv, agetty, bootctl, journalctl,
  systemd-analyze, systemd-id128, systemd-sysupdate, systemd-sysext
  (os-base.bst) and bluefin-boot-origin (boot-origin.bst).

sources:
- kind: local
  path: files/os/update-check
