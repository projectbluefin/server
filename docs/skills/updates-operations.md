---
name: updates-operations
description: How Bluefin Server nodes update and roll back at runtime. Load when debugging systemd-sysupdate features and components, the nightly reboot timers, the boot health gate, bluefin-boot-deadline, the reboot interlocks (kured, operator hold, FleetLock), or the diskless update check.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /systemd/systemd
---
# Updates: scheduling, health gate, and rollback

The boot chain, diskless pull and install architecture live in
[ddi-installer.md](ddi-installer.md); the signing and trust model in
[systemd-sysupdate-verification.md](systemd-sysupdate-verification.md). This
file is the update machinery itself.

## Updates

Installed nodes update with `systemd-sysupdate` against the transfers in
`files/os/sysupdate.d/`:

- `10-usr.transfer` and `11-usr-verity.transfer` fill the inactive usr /
  usr-verity slot (matched by `bluefin_usr_@v` partition labels).
- `20-uki.transfer` installs the new disk UKI into `/EFI/Linux` with boot
  counting (`TriesLeft=3`, at most 2 UKIs kept).
- `30-zfs.transfer`, `31-kubestellar.transfer`, `32-kubeadm.transfer`,
  `33-nvidia-open-595.transfer`, `35-homelab.transfer`,
  `36-argo-workflows.transfer` and `37-mcp.transfer` are optional **features**
  (enabled with `updatectl enable zfs` or a drop-in
  `/etc/sysupdate.d/zfs.feature.d/enable.conf` with `[Feature] Enabled=true`).
  When enabled, the matching sysext is downloaded with every OS update into
  `/var/lib/extensions` (two versions kept, `ProtectVersion=%A`); systemd-sysext
  merges only the one matching the booted image, so a boot-counted rollback
  keeps ZFS (or the NVIDIA driver).

`updatectl features` lists the optional features on installed and diskless
nodes; every QEMU boot test asserts it (`PROBE updatectl-features=ok`). Two
systemd 261 limits keep it working (#375):

- A `.feature` file carries only `Description=` (and `Enabled=`).
  `Documentation=` or `AppStream=` makes `systemd-sysupdate --json` emit a
  field updatectl's strict parser rejects, so every `updatectl features`
  fails with "Cannot assign requested address" (fixed in systemd 262).
- A diskless node mounts no `$BOOT`, so `20-uki.transfer` cannot resolve and
  sysupdated would have no host target ("Invalid target: host").
  `systemd-sysupdated.service.d/10-diskless.conf` masks that transfer in
  `/run/sysupdate.d/` on diskless boots; enabled features are fetched there
  by `bluefin-sysext-fetch` (systemd-sysext-extensions.md).

The k0s and NVIDIA Container Toolkit sysexts are separate sysupdate components
on their own version axes (`sysupdate.k0s.d/`,
`sysupdate.nvidia-container-toolkit.d/`); see `systemd-sysupdate-verification.md`.

Sources are the release assets on GitHub Releases, verified against the
GPG-signed `SHA256SUMS` with `Verify=yes` (see
`systemd-sysupdate-verification.md`).

The `/usr/libexec/bluefin-*` update and first-boot helpers named below are
symlinks to one static Go binary, `/usr/bin/bluefin-host`, which runs the
helper its name says (also as `bluefin-host <name>`; see
`ddi-installer-build.md`).

### Automatic updates on installed nodes

`files/os/systemd/system-preset/80-bluefin-updates.preset` enables FSDK's
`systemd-sysupdate.timer` (15 min after boot, then every 2 h, randomized) and
`systemd-sysupdate-reboot.timer` (04:10, randomized; two more runs where the
fleet reboot lock below is configured), which FSDK's
`90-sysupdate.preset` would otherwise disable. The timer runs the same
`systemd-sysupdate update` as a manual update, so enabled features follow the
OS in lock-step. The reboot unit runs `systemd-sysupdate reboot`, which reboots
only when a newer version than the booted one is installed.

- **Boot health gate.** The preset enables
  `systemd-boot-check-no-failures.service` (`RequiredBy=boot-complete.target`,
  after `multi-user.target`), and `systemd-bless-boot` marks a boot-counted UKI
  good only after `boot-complete.target`. A good boot is one that reaches
  `multi-user.target` with no failed unit. Only sysupdate-installed UKIs are
  counted, so diskless boots never pull in `boot-complete.target`.
  `systemd-sysupdate.service.d/30-update-status.conf` orders every update
  check after `boot-complete.target`, so an update source that cannot be
  reached never fails a unit before a counted boot is judged.
- **Rollback.** systemd-boot only moves on at the *next* boot, so the preset
  also enables `bluefin-boot-deadline.timer`. It runs on boot-counted boots
  only (the `LoaderBootCountPath` EFI variable exists; never on diskless,
  installer, blessed or uncounted boots) and fires 15 minutes after boot. If
  `systemd-bless-boot status` is still `indeterminate` (or `bad`) and
  `boot-complete.target` is not active, `/usr/libexec/bluefin-boot-deadline`
  logs the failed units and reboots, so systemd-boot uses up the next try and,
  after the third, boots the previous UKI. The last try boots as `dirty` and
  reboots only when another UKI can still be booted, so a node with nothing to
  fall back to does not loop. The service is not ordered after
  `multi-user.target`, so a boot that hangs gets the same treatment. Change the
  deadline with a drop-in (`[Timer]`, `OnBootSec=`, then `OnBootSec=30min`).
  - *On Kubernetes nodes* (kubelet or k0s starting, running or stopping) it
    does not reboot: a node that has been up for 15 minutes may carry
    workloads, so it touches `/run/reboot-required` and kured cordons, drains
    and reboots it within its cluster lock, as for an update. Each try then
    costs a drain, and without kured the node stays on the unblessed image
    until someone reboots it. When the Kubernetes unit itself is stopped or
    failed the node is `NotReady`, has nothing to drain and cannot run kured,
    so it reboots directly.
  - *Operator hold*: `/run/reboot-lock` or `/etc/reboot-lock` stops the
    reboot and the kured flag, like the nightly reboot below. With a fleet
    reboot lock configured the reboot also waits for a slot (below).
  - After a rollback, `systemd-sysupdate pending` still reports the failed
    version, which would bring the node back to it every night (or through
    kured every two hours). `/usr/libexec/bluefin-update-pending` wraps it and
    says no while that version's UKI has no tries left
    (`bluefin-server-<ver>+0-<done>.efi`); it gates the kured flag and the
    nightly reboot. The next newer release takes the failed version's slot and
    clears the block. A boot that fails in the initrd reboots on its own
    (`emergency.service.d/10-reboot.conf`).
- **Reboot interlock.** `systemd-sysupdate-reboot.service.d/20-interlock.conf`
  skips the nightly reboot when:
  - `/run/reboot-lock` (until the next boot) or `/etc/reboot-lock` (until
    removed) exists, the operator hold from
    [#182](https://github.com/projectbluefin/server/pull/182) by Bob Killen.
    Kured has its own lock and does not read these files;
  - the newest installed version already failed its boot tries
    (`bluefin-update-pending`, above);
  - `kubelet.service`, `k0scontroller.service` or `k0sworker.service` is
    running, the Kubernetes interlock also proposed in #182. Kubernetes nodes
    reboot through [kured](https://kured.dev/) (cordon, drain, one node at a
    time): `systemd-sysupdate.service.d/20-kured.conf` touches
    `/run/reboot-required` after each run once `bluefin-update-pending` reports
    an update. Without kured, a Kubernetes node keeps the staged update until
    someone reboots it.
- **Fleet reboot lock.** Hosts that serve together without Kubernetes can
  take turns: every local reboot, the nightly one and the boot deadline's,
  first takes a reboot slot from a
  [FleetLock](https://coreos.github.io/zincati/development/fleetlock/protocol/)
  server, the protocol Zincati uses on Fedora CoreOS (for example
  [poseidon/fleetlock](https://github.com/poseidon/fleetlock) or
  [coreos/airlock](https://github.com/coreos/airlock)). Configure it in
  `/etc/bluefin/reboot-lock.conf` (not shipped; write it with Ignition or by
  hand):

  ```ini
  URL=https://<fleetlock-host>/
  GROUP=web
  ```

  or with the system credentials `bluefin.reboot-lock.url` and
  `bluefin.reboot-lock.group`, which override the file. `GROUP` defaults to
  `default`. Without a URL nothing changes, so single hosts and Kubernetes
  nodes (kured) are unaffected. `/usr/libexec/bluefin-reboot-lock` is the
  client (no daemon); its client id is the machine ID hashed
  with an application key (`systemd-id128 machine-id
  --app-specific=924987751bb64ad68c398e4be4e32e2f`), and every message logs it.
  - *Acquire*: `bluefin-reboot-lock acquire` is the last `ExecCondition=` of
    `20-interlock.conf`, so a slot is requested only when the reboot would
    happen; anything but HTTP 200 (all slots taken, server unreachable) skips
    that run. `bluefin-fleet-reboot.timer` starts the reboot unit again at
    04:40 and 05:10, each with up to 30 minutes of random delay, so a group
    takes turns within one night; only nodes that have the file, or the URL
    as a system credential PID 1 received (SMBIOS, a `.cred` on the ESP), get
    these runs: a URL placed only in `/etc/credstore` still works for the
    lock but gets the single upstream run. `bluefin-boot-deadline` takes a slot
    before it reboots a counted boot and, when the server refuses one, runs
    again every 5 minutes (exit 75, `RestartForceExitStatus=`). When the server
    cannot be reached at all (the client exits 3, not 1) it reboots without a
    slot, since the update it rolls back may be what broke the network. A node
    that rebooted for an update still holds its slot, so its tries and the
    fallback are not delayed.
  - *Release*: `bluefin-reboot-lock-release.service` gives the slot back after
    `boot-complete.target`, only when `systemd-bless-boot status` is `good` or
    `clean` (not counted, e.g. the previous UKI after a rollback), and retries
    with backoff (1 minute up to 1 hour) until the server confirms. It is
    enabled in /usr, so nodes that updated into it run it too. A node whose
    boot is not blessed keeps its slot and holds back its group; release it
    from anywhere with `curl -H 'fleet-lock-protocol: true' -d
    '{"client_params":{"id":"<id>","group":"<group>"}}'
    https://<fleetlock-host>/v1/steady-state`.
- **Opting out.** `systemctl disable --now systemd-sysupdate-reboot.timer`
  stages updates without rebooting; also disable `systemd-sysupdate.timer` to
  stop updating. Presets apply on first boot only, so nodes installed before
  this preset need `systemctl preset systemd-sysupdate.timer
  systemd-sysupdate-reboot.timer systemd-boot-check-no-failures.service
  bluefin-boot-deadline.timer` once. `bluefin-update-status.service` is the
  exception: `bluefin-update-status-migrate.service` (enabled in /usr, run
  once per installed node) enables and starts it on the first boot into an
  image that ships it if it is not enabled yet. It never touches the update
  timers, so an opt-out survives updates.
- **Update health** (version, last check, staged update, last error) is on
  the console and SSH login banners; see "Update health on the node" in
  [sysupdate-operations.md](sysupdate-operations.md).

### Diskless and installer boots

Diskless nodes and the USB installer have no slots. Their `10-diskless.conf`
drop-ins condition `systemd-sysupdate.service`,
`systemd-sysupdate-reboot.service` and both timers off when
`/run/machines/rootdisk.raw` exists or the command line has `root=tmpfs`. A
diskless node updates by rebooting into whatever its boot server serves.

`bluefin-diskless-update-check.timer` (5 min after boot, then hourly; only
when `/run/machines/rootdisk.raw` exists) tells the node when that would be a
newer image. `/usr/libexec/bluefin-boot-origin`, which Ignition also uses,
finds the boot directory from the `StubDeviceURL` EFI variable, the explicit
http(s) `rd.systemd.pull=` source, or the `import.pull` credential.
`bluefin-diskless-update-check` then fetches `SHA256SUMS` and `SHA256SUMS.gpg`
from that directory, verifies them with `gpgv` against the image keyring, and
compares the `bluefin-server_<ver>.raw` entry with the running `IMAGE_VERSION`
(`systemd-analyze compare-versions`). When the release is newer and the next
boot would pull it, it touches `/run/reboot-required` and logs `Bluefin Server
<ver> is available from <url>`. That holds when the origin resolves the
version at boot: a netboot UKI served under a fixed name (Booty's
`bluefin-server-netboot.efi`, via `StubDeviceURL`) that the server swaps for
the new release. An origin that names a versioned file,
`bluefin-server_<ver>.raw` (an explicit `rd.systemd.pull=` URL or the
`import.pull` credential) or `bluefin-server-netboot_<ver>.efi`, is pinned:
the node would pull the same version again, and kured would drain and reboot
it on every check. A pinned node only logs `... but this node is pinned to
<file>; not flagging`; repoint its boot origin to update it.
Network and signature errors are logged and leave the flag alone; the unit
never fails and never reboots. Kured reboots a diskless Kubernetes node on the
flag. Other nodes wait for an operator or fleet tooling to act on it
(`test -e /run/reboot-required`,
`journalctl -u bluefin-diskless-update-check`). The boot server (Booty)
decides what the next boot pulls.

## See also

- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) — signing and trust model.
- [sysupdate-operations.md](sysupdate-operations.md) — update-health banner and key rotation.
- [ddi-installer-dogfood.md](ddi-installer-dogfood.md) — the update/rollback dogfood runs.
