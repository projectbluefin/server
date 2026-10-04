---
name: diskless-troubleshooting
description: Use when a diskless (netboot UKI) node fails to boot, reboot-loops, needs more RAM, or needs its logs kept, and when writing an Ignition config for Bluefin Server; covers the initrd failure summary, minimum RAM, network and download failure modes, getting logs, and the supported Ignition subset.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-03"
  context7-sources:
    - /systemd/systemd
---
# Diskless Boot Troubleshooting

## When to Use

- A diskless node reboots in a loop, or never reaches a login prompt.
- Sizing RAM for diskless nodes.
- Keeping logs from diskless boots.
- Writing or debugging an Ignition config (diskless or installed).

## When NOT to Use

- The boot chain, pull and install architecture itself (see
  [ddi-installer.md](ddi-installer.md)).
- Building and dogfooding images (see
  [ddi-installer-build.md](ddi-installer-build.md)).

## What a failing node prints

A failed initrd never drops to a shell (root is locked): it isolates
`emergency.target`, whose `emergency.service` drop-in
(`files/initrd/usr/lib/systemd/system/emergency.service.d/10-reboot.conf`) runs
`/usr/libexec/bluefin-boot-diagnostics failure-summary` and then reboots. The
summary lists each failed unit with a one-line hint and its last journal lines,
the network links when the network or the download failed, any ignored
`ignition.*` kernel arguments, and the last `journalctl -b -p err` lines. It is
written to every active console (`/sys/class/tty/console/active`: the monitor
and `ttyS0`), not only to `/dev/console`, which is just the last `console=`.

The summary stays up for 60 s, then the node reboots and retries. Retrying is
deliberate: a diskless node recovers unattended once the server, network or
config is fixed, and on installed nodes boot counting falls back to the
previous image. Change the delay (10 to 86400 s) with the
`bluefin.failure_delay` system credential (SMBIOS type 11, QEMU fw_cfg, or
`/loader/credentials/bluefin.failure_delay.cred` on the ESP); the
`bluefin.failure_delay=` kernel argument overrides it only where the command
line is not locked by Secure Boot. The 10 s floor keeps a persistent failure
from becoming a hot reboot loop.

Before the download, `bluefin-pull-check@.service` (wanted by
`systemd-import@.service.d/10-bluefin-pull-check.conf` and ordered before the
download) sends an HTTP HEAD to the image URL systemd-import-generator
resolved. It stops the boot, with its own framed console message, only when a
2xx answer gives a `Content-Length` that cannot fit in RAM. When it cannot
check the size (no answer, an HTTP error such as the 403 a signed
object-store URL gives to HEAD, or no `Content-Length`), it prints
`BLUEFIN: cannot check that the OS image fits in RAM (<reason>); downloading it anyway`
and the download runs: whether the image can be fetched is for systemd-import
to find out. A failed download goes straight to the summary instead of
waiting out the 300 s `/usr` device timeout.

## Minimum RAM

The netboot initrd downloads the whole OS DDI (`bluefin-server_<ver>.raw`,
540 MiB for `26.09.x`) into `/run/machines`. systemd mounts `/run` as a tmpfs
capped at 20% of RAM, and the DDI stays there for the whole boot because it
backs `/usr`. The pull check requires the DDI plus 64 MiB to fit in both the
free space of `/run` and `MemAvailable`, so usable RAM (`MemTotal`) must be at
least about five times the DDI plus 64 MiB: about 3 GiB for a 540 MiB DDI.
Measured in QEMU with the `26.09.x` DDI, `-m 3072` (2816 MiB `MemTotal`) is
refused and `-m 3584` boots. Plan on 4 GiB plus the workload. If the server
does not give the size, the check is skipped and a machine below the minimum
fails during the download instead (`systemd-import@...service` failed).

A machine below the minimum fails before the download (QEMU `-m 2048`):

```text
BLUEFIN: NOT ENOUGH RAM FOR A DISKLESS BOOT
This machine needs ~3072 MiB RAM, have 1876 MiB.
The OS image bluefin-server_26.09.2.raw (540 MiB) is downloaded into /run, a RAM
file system capped at 20% of RAM: 371 MiB free there, MemAvailable 1374 MiB.
```

## Failure modes

| Symptom in the summary | Cause | Timing |
|---|---|---|
| `systemd-networkd-wait-online.service` failed, "no network link became routable" | No DHCP answer, no carrier | `systemd-networkd-wait-online --any --timeout=300`: 300 s, then the download fails and the node reboots |
| "no network interface found" | NIC driver not in the initrd module list (`initrd-modules` in `oci/bluefin-server-boot.bst`) | As above |
| `systemd-import@...service` failed, systemd-importd says `Transfer failed: ...` | Routable link but no route to, or no answer from, the boot server | When the download starts |
| `systemd-import@...service` failed, systemd-importd says `HTTP request to ... failed with code 404.` | The DDI is not next to the netboot UKI (or at the `import.pull` URL) | When the download starts |
| "NOT ENOUGH RAM FOR A DISKLESS BOOT" | See [Minimum RAM](#minimum-ram) | Seconds |
| `systemd-import@...service` failed, with systemd-importd's reason (e.g. `DOWNLOAD INVALID: Checksum ... did not check out`) | Download interrupted, the DDI does not match `SHA256SUMS`, or `SHA256SUMS.gpg` is missing or not signed by a key in the image keyring | Right after the download |
| `systemd-veritysetup@usr.service` or `sysusr-usr.mount` failed | The DDI does not match the `usrhash=` of the UKI that booted (mixed versions on the server) | After the download |
| "No unit failed: a device or job timed out" | A device never appeared within `systemd.default_device_timeout_sec=300` | 300 s |
| `ignition-<stage>.service` failed | See [Ignition](#ignition) | During the stage |

## Getting logs from a diskless node

Every diskless boot starts with a fresh machine ID and keeps its journal in
RAM (`/run/log/journal` in the initrd, then `/var/log/journal` on the tmpfs
root), so nothing survives a reboot by default.

- **Initrd failures** never reach a disk: read the console. The netboot UKI
  sets `console=tty0 console=ttyS0,115200`; use a serial cable, IPMI
  serial-over-LAN or the BMC console log. `netconsole` is built into the
  kernel, but its `netconsole=` argument cannot be added to the sealed command
  line, so it is not available in the initrd.
- **Persistent logs** after switch-root: provision a `/var` disk with Ignition
  (`tests/fixtures/ignition/var-on-disk.ign`, the same state-disk pattern the
  boot server's per-host `bluefin-node.ign` uses; `/var/log/journal` is created
  on it by `systemd-tmpfiles`, so journald persists without extra config).
  Each boot writes under its own machine ID and plain `journalctl` shows only
  the current one, so read across boots with
  `journalctl -D /var/log/journal --list-boots` and
  `journalctl -D /var/log/journal -b -1`. Do not pin
  the ID by writing `/etc/machine-id` with Ignition: a set machine ID ends the
  first-boot state that applies the vendor presets on every diskless boot, and
  units enabled only by vendor presets stop starting. Explicit Ignition unit
  selections are applied independently of first-boot state. The
  `system.machine_id` credential (a 32-hex ID, or `firmware` for the SMBIOS UUID)
  pins it without that effect.
- **Remote logs**: the image ships `systemd-journal-upload`; an Ignition config
  can write `/etc/systemd/journal-upload.conf` (`[Upload]` / `URL=`) and enable
  `systemd-journal-upload.service` to stream the journal of the running system
  to a `systemd-journal-remote` collector. It starts after switch-root, so it
  does not cover initrd failures.

## Ignition

Configs arrive as the `ignition.config` / `ignition.config.url` credentials or
as `bluefin-node.ign` next to the netboot UKI (see
the Ignition section of [ddi-installer.md](ddi-installer.md)). Ignition kernel
arguments (`ignition.config.url=`, `ignition.platform.id=`, ...) are never read;
if any are on the command line, `bluefin-ignition-kargs.service` prints a
framed warning naming them (not their values) and the failure summary repeats
it.

Stages wired into the initrd (`files/initrd-ignition/`), in order:
`fetch-offline`, `fetch` (only when the config needs the network), `disks`,
`mount`, `files`, and `umount` (`ExecStop` of `ignition-mount.service`). The
`kargs` stage is not wired, so `kernelArguments` is silently not applied: the
command line is sealed in the signed UKI.

When the failure summary of a network-booted node lists
`bluefin-ignition-credentials.service`, the node most likely refused the
`bluefin-node.ign` next to its UKI (the rules are in "Per-node configuration"
in [booty-integration.md](booty-integration.md)). The unit's journal lines
under it say why: `gpgv`'s own reason when the signature does not verify, the
HTTP status or curl error when the signature could not be fetched, a keyring
that cannot be read, or an unsigned config without the opt-out.

| Config section | Supported |
|---|---|
| `ignition.config.merge` / `replace`, `timeouts`, `security.tls` | Yes |
| `storage.disks` (partitions via `sgdisk`) | Yes |
| `storage.filesystems` | `xfs`, `ext4`, `vfat`, `swap`; no `btrfs` |
| `storage.luks` | Key files only; no `clevis` (TPM2 / Tang) |
| `storage.raid` | No (`mdadm` absent) |
| `storage.files`, `directories`, `links` | Yes |
| `systemd.units` (contents, dropins, `enabled`) | Yes; the files stage applies Ignition's unit presets before switch-root, even with an existing machine ID |
| `passwd.users`, `passwd.groups` | Yes |
| `kernelArguments` | No |

After writing files and units, `ignition-files.service` applies the preset
selections in `20-ignition.preset` to `/sysroot` before switch-root. This works
on installed nodes with an existing machine ID as well as on a fresh diskless
root. Only units named by Ignition are preset; unrelated local enablement and
unit masks are preserved. The generated preset file is cleared before each
files stage so an older rule cannot override a changed config. A selection is
applied when it is new or changed since it was last applied to this `/etc`
(recorded in `20-ignition.preset.applied`, which systemd does not read): on
an installed node, which runs Ignition on every boot, a unit an operator
enabled or disabled since keeps that state until the config changes its
selection. A diskless node's fresh `/etc` gets every selection on every boot;
a unit that is missing or masked is retried on the next boot.

There is no first-boot marker: every diskless boot runs every stage against a
fresh `/etc`, so a config must be idempotent or the node fails the same stage
on every boot:

- **Disks**: keep `wipeTable: false` and `wipePartitionEntry: false`; an
  existing partition must match the config (number, label, size, type) or
  `ignition-disks` fails.
- **Filesystems**: `wipeFilesystem: false` reuses a filesystem with the same
  format (and label/UUID when set) and fails on any other;
  `wipeFilesystem: true` erases the disk on **every** boot.
- **Files**: a file with `contents` fails the `files` stage when something is
  already at its path and `overwrite` is false (the default): true from the
  second boot for files on a persistent filesystem, and on every boot for
  paths shipped in the factory `/etc`. Use `"overwrite": true`.

## Verification

- [ ] `just dogfood-check` passes (normal diskless boot).
- [ ] `DOGFOOD_MEM=2048 scripts/dogfood-diskless.sh dist/diskless --check`
      shows "NOT ENOUGH RAM FOR A DISKLESS BOOT" in `dist/diskless/dogfood-serial.log`.
- [ ] `DOGFOOD_TAMPER=sums scripts/dogfood-diskless.sh dist/diskless --check`
      shows "BLUEFIN: BOOT FAILED" and the failed `systemd-import@` unit.
- [ ] `python3 -m pytest tests/unit/test_initrd_diagnostics.py` passes.

## See also

- [ddi-installer.md](ddi-installer.md) — boot chain, diskless pull, Ignition credentials.
- [ddi-installer-build.md](ddi-installer-build.md) — dogfood harness and its `DOGFOOD_*` variables.
