---
name: ddi-installer
description: Use when building or debugging the Bluefin Server boot chain, the diskless network pull, the systemd-sysinstall disk install, or the A/B systemd-sysupdate flow.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-29"
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---
# Boot, Install, and Update Architecture

## When to Use

- Building or debugging the signed boot chain (UKIs, systemd-boot, Secure Boot key enrollment).
- Changing the diskless boot flow (`rd.systemd.pull`, dm-verity, initrd contents).
- Writing or refining `systemd-repart` recipes (`files/os/repart.d/`) or `systemd-sysupdate` transfers (`files/os/sysupdate.d/`).
- Working on the Ignition opt-in path (`elements/ignition/`, `files/initrd-ignition/`).

## When NOT to Use

- k0s or OpenZFS sysext work (see `k0s-sysext.md`, `systemd-sysext-extensions.md`).
- Release signing and sysupdate verification keys (see `systemd-sysupdate-verification.md`).

## One build, one version, one release set

`oci/bluefin-server-image.bst` produces every release artifact for one
`image-version` (`include/image.yml`, set per build by `just set-version`,
`YY.MM.<run>` on main, `0.<run>` on PRs, at most 17 characters so it fits a
GPT partition label with room to spare):

| Artifact | Role |
|---|---|
| `bluefin-server_<ver>.raw` | OS DDI: `/usr` erofs partition, its dm-verity hash partition, and an ESP carrying the disk UKI plus the install-time `repart.d`. Diskless nodes pull it into RAM; booted diskless it is also the installer payload. |
| `bluefin-server_<ver>_<uuid>.usr.raw` / `...usr-verity.raw` | `systemd-sysupdate` sources for the usr and verity slots; the `<uuid>` in the name is the partition UUID derived from the usrhash. |
| `bluefin-server-<ver>.efi` | Disk UKI (installed nodes); also the sysupdate source for `$BOOT`. |
| `bluefin-server-netboot_<ver>.efi` | Netboot UKI (diskless nodes); the UEFI HTTP boot / PXE target. |
| `bluefin-server-netboot_<ver>.esp.raw` | Netboot ESP image: signed systemd-boot, the netboot UKI, and Secure Boot key enrollment payloads. Write it to a USB stick to boot diskless without HTTP boot. |
| `bluefin-server-installer_<ver>.raw` | Offline USB installer: the same usr + verity images (labelled `bluefin-installer-usr` / `bluefin-installer-usr-verity`) plus an ESP with signed systemd-boot, the installer UKI, key enrollment payloads, and the disk UKI + install-time `repart.d` under `bluefin/`. Write it to a USB stick to install without a network. |
| `zfs_<ver>.raw.zst` / `kubestellar_<ver>.raw.zst` / `kubeadm_<ver>.raw.zst` | Opt-in sysext assets locked to this image version; installed nodes fetch them through the `zfs` / `kubestellar` / `kubeadm` sysupdate features. |
| `k0s-<k0s-ver>.raw.zst` | Opt-in k0s sysext asset, on its own version axis. |
| `efi-keys/` | PK/KEK/db enrollment payloads. |
| `SHA256SUMS` / `SHA256SUMS.gpg` | One manifest over every file above, signed in-element with `files/boot-keys/sysupdate-signing.asc`; the image trusts the matching `import-pubring.pgp` (see `systemd-sysupdate-verification.md`). |

A release is this directory published as-is: a GitHub Release `v<ver>` plus an
ORAS OCI artifact `ghcr.io/<owner>/bluefin-server:<ver>,latest` (one layer per
file, artifact type `application/vnd.projectbluefin.server.release.v1`).
`just publish-oci REF [DIR] [PLAIN_HTTP]` pushes the same artifact locally, as
a rehearsal; CI publishes through `scripts/publish-release.sh`, which also
verifies the pushed manifest against the local files.

The /usr image itself is built by `oci/bluefin-server-usr.bst` with an offline
`systemd-repart`: an erofs partition (`bluefin_usr_<ver>`) plus its dm-verity
hash partition (`bluefin_usr_verity_<ver>`), and the root hash is recorded in
`bluefin-server_<ver>.usrhash`. `/etc` is empty on every boot; its defaults
live in `/usr/share/factory/etc` and are copied in by `systemd-tmpfiles`.

## The boot chain

All UKIs are built by `oci/bluefin-server-boot.bst` from the FSDK kernel
(`bluefin-server/kernel-modules.bst`, modules signed with our module key) and a
systemd-native initrd (no dracut; `bluefin-server/initrd/initrd-stack.bst`).
They all pin `usrhash=` of the same /usr image on their command lines and are
signed with DB, so Secure Boot locks those command lines. `lockdown=integrity`
is always on. `os-sd-boot-signed.bst` signs systemd-boot with the same DB key
so installed disks and the netboot ESP get a loader firmware accepts.

Dev keys come from `just gen-dev-keys` (throwaway keys in the gitignored
`files/boot-keys/`, including the `sysupdate-signing.asc` /
`import-pubring.pgp` pair that signs and verifies `SHA256SUMS`); CI builds on
main use the `BOOT_KEYS_TARBALL` and `SYSUPDATE_SIGNING_KEY` secrets.

### Diskless (netboot UKI)

```text
firmware -> signed systemd-boot -> bluefin-server-netboot_<ver>.efi
  -> initrd: network up (DHCP), systemd-importd pulls
     bluefin-server_<ver>.raw into RAM (rd.systemd.pull ... blockdev:rootdisk)
  -> systemd-veritysetup opens /usr from the loop partitions, checked against usrhash=
  -> switch root: tmpfs /, read-only erofs /usr
```

The pull source is the UEFI HTTP boot origin (`bootorigin:`) or the
`import.pull` system credential (SMBIOS type 11, QEMU fw_cfg, or ESP
`/loader/credentials`). The pull runs with `verify=signature`: the initrd
ships gnupg and the image keyring, and importd fetches `SHA256SUMS` and
`SHA256SUMS.gpg` from the image's directory and checks the signature before
using the manifest. The manifest hash check pins the DDI, the signed UKI pins
`usrhash=`, and dm-verity checks every `/usr` block against it; a tampered DDI
or a re-hashed unsigned manifest is refused. A failed boot never drops to an
emergency shell: the initrd prints a failure summary on every console and
reboots (`files/initrd/usr/lib/systemd/system/emergency.service.d/10-reboot.conf`),
which is what lets boot counting work unattended. Before the pull, a check
refuses an image that cannot fit in RAM. What the node prints, minimum RAM,
failure modes and logs: [diskless-troubleshooting.md](diskless-troubleshooting.md).

### UEFI HTTP boot

With UEFI HTTP boot the firmware fetches `bluefin-server-netboot_<ver>.efi`
directly from the boot server; no systemd-boot runs. systemd-stub records the
boot URL in the `StubDeviceURL` EFI variable, and the initrd derives the URL
of `bluefin-server_<ver>.raw` (and of `SHA256SUMS` / `SHA256SUMS.gpg`) from
the same directory. `bluefin-ignition-credentials` also uses it: with no
`ignition.config` / `ignition.config.url` credential it HEADs
`bluefin-node.ign` next to the UKI and applies it through `config.replace`
when present. Because HTTP boot skips systemd-boot's key enrollment, the
firmware must already trust the image DB key; `scripts/dogfood-diskless.sh`
with `DOGFOOD_BOOT=http` enrolls once from the netboot ESP first.

### Installed disk (disk UKI)

```text
firmware -> systemd-boot -> bluefin-server-<ver>.efi
  -> /usr slot found by partition label (bluefin_usr_<ver>) and the
     verity-derived UUIDs baked into the install-time repart.d
  -> persistent xfs root found by systemd gpt-auto discovery
```

Boot entries are counted (`bluefin-server-<ver>+3-0.efi`): after three failed
boots of a new image systemd-boot falls back to the previous UKI. That is the
automatic rollback path.

## Installing to disk

Both install paths run stock `systemd-sysinstall` with the disk layout from
`files/os/repart.d/` (ESP, usr slot A + verity copied from the running image,
empty slot B, persistent xfs root), exported as `bluefin/repart.d` with slot A's
UUIDs pinned to the usrhash derivation by `bluefin-server-boot.bst`.
`systemd-sysinstall` writes the ESP and slot A and links the disk UKI; the
first boot of the installed disk runs the initrd's `systemd-repart` (reading
`/sysusr/usr/lib/repart.d`) to create slot B and the persistent root. The
installed disk is identical whichever path installed it. No shell installer.

### From the USB installer (offline)

```bash
sudo dd if=bluefin-server-installer_<ver>.raw of=/dev/<usb> bs=4M conv=fsync status=progress
```

```text
firmware -> systemd-boot -> bluefin-server-installer_<ver>.efi
  -> /usr from the stick's bluefin-installer-usr partition (dm-verity, usrhash=)
  -> tmpfs root, systemd.unit=system-install.target
  -> systemd-sysinstall.service on the monitor (/dev/console = tty0)
```

The installer UKI finds its /usr by partition label, not by the
usrhash-derived UUIDs. Those UUIDs belong to installed usr slots, so an
existing Bluefin install (including the disk being overwritten) is never opened
as the installer's /usr, and an installed node booted with the stick still
plugged in never opens the stick's usr. `run-bluefin-installer.mount` mounts
the stick's ESP (`bluefin-installer`) at `/run/bluefin/installer`; the
`systemd-sysinstall.service` drop-in passes
`--definitions=/run/bluefin/installer/bluefin/repart.d` and
`--kernel=${BLUEFIN_INSTALL_KERNEL}` (the disk UKI, named by the installer
UKI's `systemd.setenv=`). The disk UKI sits outside `EFI/Linux` on the stick so
systemd-boot never offers it there. sysinstall prompts for the target disk,
erasing it, and confirmation, then reboots; remove the stick when it does.

Secure Boot: the stick's systemd-boot and UKIs are signed with the project DB
key. On bare metal put the firmware into Setup Mode and pick the enrollment
entry in the systemd-boot menu (`secure-boot-enroll if-safe` only
auto-enrolls in VMs), or turn Secure Boot off.

### From a diskless node

A running diskless node is also an installer. The OS DDI's ESP partition is
mounted at `/run/bluefin/boot` (`run-bluefin-boot.mount`):

```bash
systemctl start run-bluefin-boot.mount
kernel="$(ls /run/bluefin/boot/EFI/Linux/bluefin-server-[0-9]*.efi)"
systemd-sysinstall --kernel="${kernel}" \
    --definitions=/run/bluefin/boot/bluefin/repart.d /dev/sdX
```

## Updates

Installed nodes update with `systemd-sysupdate` against the transfers in
`files/os/sysupdate.d/`:

- `10-usr.transfer` and `11-usr-verity.transfer` fill the inactive usr /
  usr-verity slot (matched by `bluefin_usr_@v` partition labels).
- `20-uki.transfer` installs the new disk UKI into `/EFI/Linux` with boot
  counting (`TriesLeft=3`, at most 2 UKIs kept).
- `30-zfs.transfer` and `31-kubestellar.transfer` are optional **features**
  (enabled with `updatectl enable zfs` or a drop-in
  `/etc/sysupdate.d/zfs.feature.d/enable.conf` with `[Feature] Enabled=true`).
  When enabled, the matching sysext is downloaded with every OS update into
  `/var/lib/extensions` (two versions kept, `ProtectVersion=%A`); systemd-sysext
  merges only the one matching the booted image, so a boot-counted rollback
  keeps ZFS.

Sources are the release assets on GitHub Releases, verified against the
GPG-signed `SHA256SUMS` with `Verify=yes` (see
`systemd-sysupdate-verification.md`).

### Automatic updates on installed nodes

`files/os/systemd/system-preset/80-bluefin-updates.preset` enables FSDK's
`systemd-sysupdate.timer` (15 min after boot, then every 2 h, randomized) and
`systemd-sysupdate-reboot.timer` (04:10, randomized), which FSDK's
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
    reboot and the kured flag, like the nightly reboot below.
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
- **Opting out.** `systemctl disable --now systemd-sysupdate-reboot.timer`
  stages updates without rebooting; also disable `systemd-sysupdate.timer` to
  stop updating. Presets apply on first boot only, so nodes installed before
  this preset need `systemctl preset systemd-sysupdate.timer
  systemd-sysupdate-reboot.timer systemd-boot-check-no-failures.service
  bluefin-boot-deadline.timer` once.

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

## Ignition (opt-in)

Ignition (v2.27.0, built from source in `elements/ignition/`) runs in the
initrd, adapted from the upstream dracut units into
`files/initrd-ignition/`. Because the kernel command line is locked inside the
signed UKI, the `ignition.config.url=` karg cannot be used; configs arrive as
**system credentials**:

- `ignition.config` — an inline Ignition JSON (or Butane YAML) config.
- `ignition.config.url` — a URL; wrapped into a `config.replace` stub and
  fetched once the network is online.

`bluefin-ignition-credentials` stages whichever is set into
`/run/ignition/user.ign`; the downstream Ignition units are conditioned on
that file, so a node with no config runs none of it. A UEFI HTTP-booted node
needs no credential: the script reads the boot URL from the `StubDeviceURL`
EFI variable and, when the server offers `bluefin-node.ign` next to the UKI,
applies it. Ignition runs on **every** boot (there is no first-boot marker on
a tmpfs root), so configs must be idempotent. See
`tests/fixtures/ignition/var-on-disk.ign` for a dogfood-tested example
(persistent /var on a second disk plus an SSH key). The supported stages and
config sections, the idempotency rules, and the warning for ignored
`ignition.*` kernel arguments are in
the Ignition section of [diskless-troubleshooting.md](diskless-troubleshooting.md).

## PXE / HTTP boot service

The intended network boot server is [Booty](https://github.com/jeefy/booty).
Its `feat/bluefin-http-boot` work (not yet merged) syncs `v<ver>` releases
from GitHub Releases or from the OCI artifact (`--bluefinOCI`, `--plain-http`
for plain-HTTP registries), checks the signature with `--bluefinKeyring`,
answers ProxyDHCP with an `HTTPClient` offer pointing at
`http://<booty>/bluefin/<mac>/bluefin-server-netboot.efi`, and serves the UKI,
the OS DDI, `SHA256SUMS(.gpg)`, and a per-host `bluefin-node.ign` (hostname,
SSH keys, state disk, extensions, k0s token). Its `doInstall` flag boots the
node into `booty-install.service`, which runs `systemd-sysinstall` against the
local disk. Without Booty, writing `bluefin-server-netboot_<ver>.esp.raw` to a
USB stick boots a node diskless the same way, provided an `import.pull.cred`
credential is placed in `/loader/credentials/import.pull.cred` on the stick
specifying the URL to pull `bluefin-server_<ver>.raw` and its signed SHA256SUMS.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script installer is simpler." | Installation stays `systemd-sysinstall`-native; the diskless boot already carries everything it needs. No shell installers. |
| "Hardcode `root=/dev/vda2` for QEMU." | Bare metal has different device names. Boot and root selection uses discoverable partition labels and verity-derived UUIDs. |
| "Kernel image is at `/boot/vmlinuz`." | FSDK installs kernels into `/usr/lib/modules/<kver>/vmlinuz`; `bluefin-server-boot.bst` picks it up from there for ukify. |
| "The initrd needs dracut." | The initrd is a hand-assembled systemd userspace (`initrd-stack.bst`) packed as newc cpio + zstd. No dracut anywhere in the tree. |
| "The diskless pull is unverified." | The initrd pulls with `verify=signature` against the keyring it ships; the signed UKI also pins `usrhash=`, and dm-verity checks every `/usr` block read. |
| "Ignition needs a karg." | The cmdline is sealed in the signed UKI. Ignition configs arrive as `ignition.config` / `ignition.config.url` system credentials, or as `bluefin-node.ign` next to the UKI on a UEFI HTTP boot; `ignition.*` kargs are ignored with a console warning. |
| "Diskless nodes need sysupdate." | Diskless nodes update by rebooting into a newer image; sysupdate is disabled when booted diskless, and `bluefin-diskless-update-check` only flags that a newer image is being served. |
| "The update timer should reboot Kubernetes nodes too." | Kubernetes nodes reboot through kured (drain first); the reboot unit's `ExecCondition=` stands down while kubelet or k0s runs. |
| "Boot counting alone rolls back a bad update." | Only on the next boot. `bluefin-boot-deadline.timer` supplies that reboot when a counted boot misses `boot-complete.target`, and `bluefin-update-pending` keeps the node from rebooting into the failed version again. |
| "Flag every diskless node when a newer release is served." | Only when the next boot would pull it; a pinned origin (`bluefin-server_<ver>.raw`) would pull the same version and loop kured. |

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] `just dogfood-check` passes (diskless boot, Secure Boot, no failed units).
- [ ] `just dogfood-install NEXT=<dir>` passes (install, disk boot with both update timers enabled, A/B update through `systemd-sysupdate.service` with the kured flag and interlock, blessed after `boot-complete.target`).
- [ ] `just dogfood-check` reports `PROBE update-check=success` for the diskless update check.
- [ ] `DOGFOOD_BROKEN=unit scripts/dogfood-install.sh <dir> <next> <broken>` passes (a unit failing on `<broken>`: three deadline reboots, fallback to `<next>`, then no kured flag and no nightly reboot).
- [ ] UKIs pin `usrhash=` and are signed with DB; `sbverify` passes in `bluefin-server-boot.bst`.
- [ ] No hardcoded device paths in any boot configuration.
- [ ] No element named `bluefin-server-ddi` or `bluefin-server-installer` exists; the OS DDI comes from `oci/bluefin-server-image.bst`.

## See also

- [ddi-installer-build.md](ddi-installer-build.md) — local build, export, and dogfood workflow.
- [diskless-troubleshooting.md](diskless-troubleshooting.md) — failure summary, minimum RAM, logs, supported Ignition subset.
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) — release signing and transfer verification.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (OS DDI, Netboot UKI, Disk UKI, Slot).
- `systemd-sysinstall(8)`, `systemd-repart(8)`, `systemd-sysupdate(8)`, `bootctl(1)`, `ukify(1)`
