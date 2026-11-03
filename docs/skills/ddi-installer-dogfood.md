---
name: ddi-installer-dogfood
description: Boot-test the Bluefin Server image set in QEMU with Secure Boot (dogfood). Load when running or debugging `just dogfood*`, `scripts/dogfood-*.sh`, the `DOGFOOD_*` environment variables, or the interactive-console install checks.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /systemd/systemd
---
# Dogfood: boot it in QEMU

Build and export first: [ddi-installer-build.md](ddi-installer-build.md). All
dogfood paths boot with Secure Boot firmware (OVMF secboot). The firmware
starts in setup mode; systemd-boot enrolls the dev keys from the ESP
(`secure-boot-enroll if-safe`) and reboots, so every later boot is verified.
`--check` fails if the guest did not boot with Secure Boot enabled: some OVMF
builds (Ubuntu 26.04's 2025.11) refuse the enrollment and would otherwise boot
on in setup mode, verifying nothing. Point `OVMF_CODE` / `OVMF_VARS` at
another build (Fedora's `edk2-ovmf` works) if yours does.

```bash
just dogfood                     # interactive diskless boot of dist/diskless/
just dogfood-check               # headless: pass when the in-guest probe
                                 # reports no failed units
just dogfood-install             # diskless boot, systemd-sysinstall to a blank
                                 # disk, then boot the installed disk
just dogfood-install NEXT=<dir>  # ...then sysupdate A->B to NEXT and boot it
just dogfood-installer           # offline USB installer: unattended install to a blank disk, boot it with and without the stick
just dogfood-installer NEXT=<dir> # ...then failed checks on the banner, sysupdate to NEXT and boot it
DOGFOOD_TARGET=prior-install just dogfood-installer  # ...then install again over that install and boot it
DOGFOOD_TARGET=foreign-gpt just dogfood-installer    # install over another OS's GPT disk (also: ext4, xfs on the whole disk)
DOGFOOD_INSTALL=console just dogfood-installer      # typed at the monitor: disk by number, "installed" screen, root password and tty1 login
DOGFOOD_INSTALL=console DOGFOOD_CONSOLE_NOISE=1 just dogfood-installer  # ...while the guest logs kernel and journal errors: none may reach the disk, summary or done screen
DOGFOOD_INSTALL=console DOGFOOD_CONSOLE_FAILURE=kernel just dogfood-installer  # ...but sysinstall fails on a missing disk UKI before any disk write: error on the monitor, machine up, journal kept
DOGFOOD_INSTALL=console DOGFOOD_CONSOLE_HOLD=8 just dogfood-installer  # ...holding each prompt on the monitor 8 s (2-8, default 3)
DOGFOOD_PROFILE=home-server DOGFOOD_INSTALL=console just dogfood-installer # Home options, nonroot owner creation/login, SSH Brew and host-engine workloads
```

`scripts/dogfood-installer.sh` recreates `DOGFOOD_STATE` (default
`dist/dogfood-installer`) on every run; use a disposable path. Any
`systemd.unit-dropin.systemd-sysinstall.service` credential makes an install
unattended and skips the disk question; never use one to instrument an
attended run.

`scripts/dogfood-diskless.sh <dir> [--check]` boots the way a PXE/HTTP-booted
node would: signed systemd-boot -> signed netboot UKI -> initrd pulls
`bluefin-server_<ver>.raw` over HTTP into RAM -> dm-verity /usr, tmpfs root.
Useful environment variables:

- `DOGFOOD_IGNITION=<file>` — pass an Ignition config as the `ignition.config`
  credential (see `tests/fixtures/ignition/var-on-disk.ign`).
- `DOGFOOD_CREDS=<dir>` — pass every file in `<dir>` as a system credential
  named after the file (SMBIOS type 11).
- `DOGFOOD_STATE_DISK=<file>` — attach a persistent second disk (`/dev/vdb`).
- `DOGFOOD_VARS=<file>` — persistent UEFI variable store (keeps enrolled keys
  across runs).
- `DOGFOOD_BOOT=disk` — boot `DOGFOOD_STATE_DISK` instead of the netboot ESP.
- `DOGFOOD_BOOT=http` — UEFI HTTP boot the netboot UKI; the initrd derives the
  `/usr` image URL from the boot URL. Enrolls the Secure Boot keys from the
  netboot ESP once per variable store first.
- `DOGFOOD_BOOT_URL=<url>` — HTTP boot from another server (e.g. Booty)
  instead of the built-in one.
- `DOGFOOD_NODE_IGN=<file>` — serve it as `bluefin-node.ign` next to the
  UKI, unsigned unless `DOGFOOD_NODE_IGN_SIG=<file>` names its
  `bluefin-node.ign.gpg` (`scripts/sign-node-config.sh
  files/boot-keys/ignition-signing.asc <file>`). An unsigned config is applied
  only through the netboot UKI's transitional `bluefin.ignition.allow-unsigned`
  default (see "Per-node configuration" in
  [booty-integration.md](booty-integration.md)).
- `DOGFOOD_REFUSAL=<ERE>` — `--check` passes only if the boot is refused
  before the probe runs, with a console line matching `<ERE>` (e.g. a node
  config the initrd will not apply).
- `DOGFOOD_SERVE_EXTRA=<dir>` — also serve the files in `<dir>`.
- `DOGFOOD_TAMPER=raw|sums` — serve a corrupted DDI (`raw`), or the corrupted
  DDI with `SHA256SUMS` re-hashed to match it, so only `SHA256SUMS.gpg` no
  longer fits (`sums`). `--check` then passes only if the initrd's pull
  refuses it for that reason (checksum mismatch, bad signature) after the
  image and both manifest files were served, and nothing booted. Credential
  drop-ins copy `systemd-importd`'s messages to the serial console.
- `DOGFOOD_MEM=<MiB>` — guest RAM (default 4096); below the diskless minimum
  the boot must fail with the RAM message (see `diskless-troubleshooting.md`).
- `DOGFOOD_EXTRA_PROBE=<file>` — shell snippet appended to the in-guest probe.
- `DOGFOOD_PROBE_LOG=<file>` — write the probe's output there while it runs,
  for a caller that reacts to it (`dogfood-homelab-templates.sh` reads the
  control plane's join passphrase from it).
- `DOGFOOD_EXPECT=<ERE>` — `--check` also requires the probe output to match,
  e.g. with `tests/fixtures/ignition/apply-marker.ign` and its `.probe`:
  `PROBE ignition marker=applied unit=active enabled=enabled ran=yes`.
- `DOGFOOD_PORT`, `DOGFOOD_MEM`, `DOGFOOD_TIMEOUT` — HTTP port (8765), guest
  memory in MiB (4096), `--check` deadline in seconds (600).

Every diskless `--check` boot also runs `bluefin-diskless-update-check` once
and reports `PROBE update-check=<result> flag=<set|none>`. Its origin is the
versioned `import.pull` file, so a newer release in the served directory only
logs that the node is pinned; an HTTP boot through a fixed-name UKI
(`DOGFOOD_BOOT=http`, `DOGFOOD_BOOT_URL=.../bluefin-server-netboot.efi`)
sets the flag.

`scripts/dogfood-install.sh <dir> [<next-dir> [<broken-dir>]]` is the full
end-to-end check: install from a diskless boot, boot the installed disk,
`systemd-sysupdate` A->B to `<next-dir>` through `systemd-sysupdate.service`
(the unit the timer starts) with the default `Verify=yes` against the signed
manifest (with the `zfs` feature enabled, so the ZFS sysext follows the OS in
lock-step), then asserts the kured flag, the Kubernetes reboot interlock, both
timers enabled and the new UKI blessed after `boot-complete.target`, and with
`<broken-dir>` break the update and confirm boot counting rolls the node back
to `<next-dir>` on its own, with the matching ZFS sysext still merged.
`DOGFOOD_SYSEXT=nvidia` enables the `nvidia-open-595` feature instead of `zfs`
and the NVIDIA Container Toolkit component with
`nvidia-container-toolkit-activate.service`; after the update and after the
rollback the driver sysext for the booted version must be merged with its
units skipped (no GPU in QEMU), `bluefin-sysext-modules nvidia` must load the
signed modules as far as the driver's `No NVIDIA GPU found`, and the toolkit
must be fetched and merged. `DOGFOOD_SYSEXT=zfs,nvidia` enables both features
and asserts both sets, with the `zfs` module loaded.
`just dogfood-install <next-dir> <broken-dir>` runs the whole sequence.
`DOGFOOD_BROKEN=slot` (default) corrupts the updated usr slot, so the initrd
fails. `DOGFOOD_BROKEN=unit` adds a unit that fails on `<broken-dir>`'s version
only and shortens the boot deadline (`DOGFOOD_DEADLINE`, default `2min`): each
counted boot reaches `multi-user.target`, misses `boot-complete.target`, and
`bluefin-boot-deadline` reboots it. The run asserts three such boots, the
fallback boot with the deadline timer inactive, and then no kured flag and a
skipped `systemd-sysupdate-reboot.service` for the failed version. `<next-dir>` and `<broken-dir>` are
ordinary image sets with higher versions, e.g.
`just set-version <next> && just export-image dist/diskless-next` (and a
higher one into `dist/diskless-broken`); the script breaks the
broken set itself. The versions must also sort above `1.<ver>` for systemd-boot: the
Type #1 entry `systemd-sysinstall` writes for the installed image carries
`version 1.<ver>` (`bluefin-server-commit_1.<ver>.conf`), so after
installing `0.674` an update to `0.674.1` still boots `0.674`; use `1.674.1`.
Release versions (`YY.MM.<run>`) sort above it. Which of these scenarios CI runs is listed in
[ci-tooling.md](ci-tooling.md) (the `boot-test` job); `scripts/ci/boot-test.sh --list`
prints the exact calls.

## See also

- [ddi-installer-build.md](ddi-installer-build.md) — build, export, prune, release.
- [diskless-troubleshooting.md](diskless-troubleshooting.md) — what a failing
  node prints.
