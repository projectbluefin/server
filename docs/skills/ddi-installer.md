---
name: ddi-installer
description: Use when building or debugging the Bluefin Server boot chain, the diskless network pull, the systemd-sysinstall disk install, or the A/B systemd-sysupdate flow.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-18"
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
| `bluefin-server-installer_<ver>.raw` | Offline USB installer; write to a stick to install without a network. See [usb-installer.md](usb-installer.md). |
| `zfs_<ver>.raw.zst` / `kubeadm_<ver>.raw.zst` / `homelab_<ver>.raw.zst` / `argo-workflows_<ver>.raw.zst` / `mcp_<ver>.raw.zst` / `kubestellar_<ver>.raw.zst` / `nvidia-open-595_<ver>.raw.zst` | Opt-in sysext assets locked to this image version; installed nodes fetch them through the sysupdate features of the same names (the last three before `nvidia` are the homelab add-ons, [homelab-profile.md](homelab-profile.md)). |
| `k0s-<k0s-ver>.raw.zst` | Opt-in k0s sysext asset, on its own version axis. |
| `nvidia-container-toolkit-<ctk-ver>.raw.zst` | Opt-in NVIDIA Container Toolkit (CDI) sysext asset, on its own version axis like k0s. |
| `efi-keys/` | PK/KEK/db enrollment payloads. |
| `SHA256SUMS` / `SHA256SUMS.gpg` | One manifest over every file above, signed in-element with `files/boot-keys/sysupdate-signing.asc`; the image trusts the matching `import-pubring.pgp` (see `systemd-sysupdate-verification.md`). |

A release publishes this directory as-is (GitHub Release `v<ver>` plus an ORAS
OCI artifact); see the `release` job in [ci-tooling.md](ci-tooling.md).
`just publish-oci REF [DIR] [PLAIN_HTTP]` pushes the same artifact locally, as
a rehearsal; CI publishes through `scripts/publish-release.sh`, which also
verifies the pushed manifest against the local files.

The /usr image itself is built by `oci/bluefin-server-usr.bst` with an offline
`systemd-repart`: an erofs partition (`bluefin_usr_<ver>`) plus its dm-verity
hash partition (`bluefin_usr_verity_<ver>`), and the root hash is recorded in
`bluefin-server_<ver>.usrhash`. `/etc` holds no image content: its defaults
live in `/usr/share/factory/etc` and are copied in by `systemd-tmpfiles`. A
diskless node keeps `/etc` on tmpfs, so it starts empty on every boot; a disk
install keeps it on the root partition (`files/os/repart.d/50-root.conf`),
where it persists across A/B updates.

## The boot chain

All UKIs are built by `oci/bluefin-server-boot.bst` from the FSDK kernel
(`bluefin-server/kernel-modules.bst`, modules signed with our module key) and a
systemd-native initrd (no dracut; `bluefin-server/initrd/initrd-stack.bst`).
They all pin `usrhash=` of the same /usr image on their command lines and are
signed with DB, so Secure Boot locks those command lines. `lockdown=integrity`
is always on. `os-sd-boot-signed.bst` signs systemd-boot with the same DB key
so installed disks and the netboot ESP get a loader firmware accepts.

The signing keys (dev vs CI, and the pair that signs and verifies
`SHA256SUMS`): [secure-boot-keys.md](secure-boot-keys.md) and
[systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).

### Shim path (`-o shim True`, off by default)

With the `shim` project option the netboot and installer ESPs boot shim
(built from source with the DB certificate as its vendor certificate; build,
SBAT and shim-review in "Shim" of [secure-boot-keys.md](secure-boot-keys.md)):

```text
firmware -> EFI/BOOT/BOOTX64.EFI (shim, DB-signed; Microsoft-signed once reviewed)
  -> \EFI\systemd\systemd-bootx64.efi (DB-signed systemd-boot, shim's DEFAULT_LOADER)
  -> UKI, verified through shim against the vendor certificate or db
```

`EFI/BOOT/mmx64.efi` (MokManager) sits next to shim; the fallback loader
does not, so booting a stick never writes firmware boot entries. loader.conf
keeps `secure-boot-enroll if-safe`: firmware in Setup Mode does not check
shim, systemd-boot enrolls the Bluefin keys, and the DB-signed shim boots
with them afterwards. Default builds lay out the ESPs exactly as before.

Not wired yet, so the option is groundwork rather than an enrollment-free
path:

- **Installed disks.** `systemd-sysinstall` runs `bootctl install`, which
  writes systemd-boot to `EFI/BOOT/BOOTX64.EFI` and registers a firmware
  boot entry for `\EFI\systemd\systemd-bootx64.efi`, so an installed disk
  boots systemd-boot directly, as without the option. Shim there needs
  `EFI/bluefin-server/` (shim, MokManager, `BOOTX64.CSV`) with the boot
  entry on shim; `bootctl update` already leaves a non-systemd-boot
  `BOOTX64.EFI` alone.
- **Microsoft-only firmware.** Until shim is Microsoft-signed it boots only
  where the Bluefin db is enrolled, and the USB installer's Secure Boot
  check still refuses firmware that lacks the Bluefin db.
- **UEFI HTTP boot** loads the netboot UKI directly, without shim. shim
  fetches `DEFAULT_LOADER` relative to its own URL when HTTP-booted; serving
  a shim chain that way is Booty-side work.

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
`ignition.config` / `ignition.config.url` credential it looks for
`bluefin-node.ign` next to the UKI and applies it only as "Per-node
configuration" in [booty-integration.md](booty-integration.md) allows.
Because HTTP boot skips systemd-boot's key enrollment, the firmware must
already trust the image DB key; `scripts/dogfood-diskless.sh` with
`DOGFOOD_BOOT=http` enrolls once from the netboot ESP first.

### Installed disk (disk UKI)

```text
firmware -> systemd-boot -> bluefin-server-<ver>.efi
  -> /usr slot found by the partition UUIDs dm-verity derives from usrhash=
     (baked into the install-time repart.d); the bluefin_usr_<ver> label
     is for sysupdate
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

Erasing a disk that is not empty needs the kernel to forget that disk's
partition devices first (systemd-repart v261, #359; why in
[usb-installer.md](usb-installer.md)). The USB installer does that itself. On
a diskless node, give `systemd-sysinstall` an empty disk, or run
`partx --delete /dev/sdX` on the target first (nothing on the disk changes).

### From the USB installer (offline)

See [usb-installer.md](usb-installer.md) — the offline installer image, its
boot flow, unattended installs, and install-time provisioning.

### From a diskless node

A running diskless node is also an installer. The OS DDI's ESP partition is
mounted at `/run/bluefin/boot` (`run-bluefin-boot.mount`), and its
`bluefin/repart.d` copies `usr` and `usr-verity` block-for-block from the
in-RAM DDI partitions (`/dev/disk/by-loop-ref/rootdisk.raw-part1` and `part2`):

```bash
systemctl start run-bluefin-boot.mount
kernel="$(ls /run/bluefin/boot/EFI/Linux/bluefin-server-[0-9]*.efi)"
systemd-sysinstall --kernel="${kernel}" \
    --definitions=/run/bluefin/boot/bluefin/repart.d /dev/sdX
```

On older image builds whose `repart.d` used `CopyBlocks=auto`, active system
extensions (`systemd-sysext`, e.g. ZFS or k0s) turn `/usr` into an overlayfs,
causing `systemd-repart` to fail with "Failed to resolve automatic CopyBlocks=
path for partition type usr". Unmerging extensions first (`systemd-sysext
unmerge`) restores `/usr` to the underlying dm-verity block device and allows
sysinstall to succeed.

## Updates

The update machinery — sysupdate features and components, the reboot timers,
boot health gate, `bluefin-boot-deadline`, the kured/operator/FleetLock
interlocks, and the diskless update check — lives in
[updates-operations.md](updates-operations.md).

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
that file, so a node with no config runs none of it. A network-booted node
needs no credential: a `bluefin-node.ign` next to its UKI is staged only as
"Per-node configuration" in [booty-integration.md](booty-integration.md)
allows. Ignition runs on **every** boot (there is no first-boot marker on
a tmpfs root), so configs must be idempotent. See
`tests/fixtures/ignition/var-on-disk.ign` for a dogfood-tested example
(persistent /var on a second disk plus an SSH key). The supported stages and
config sections, the idempotency rules, and the warning for ignored
`ignition.*` kernel arguments are in
the Ignition section of [diskless-troubleshooting.md](diskless-troubleshooting.md).

## PXE / HTTP boot service

The intended network boot server is [Booty](https://github.com/jeefy/booty)
(Bluefin support on its `main` since
[#39](https://github.com/jeefy/booty/pull/39)). It syncs `v<ver>` releases
from GitHub Releases or from the OCI artifact (`--bluefinOCI`, plain-HTTP
registries via an `http://` prefix), checks the signature with
`--bluefinKeyring`, answers ProxyDHCP with an `HTTPClient` offer pointing at
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

- [updates-operations.md](updates-operations.md) — update timers, health gate, rollback, interlocks.
- [ddi-installer-build.md](ddi-installer-build.md) — local build and export.
- [ddi-installer-dogfood.md](ddi-installer-dogfood.md) — QEMU dogfood workflow.
- [diskless-troubleshooting.md](diskless-troubleshooting.md) — failure summary, minimum RAM, logs, supported Ignition subset.
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) — release signing and transfer verification.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (OS DDI, Netboot UKI, Disk UKI, Slot).
- `systemd-sysinstall(8)`, `systemd-repart(8)`, `systemd-sysupdate(8)`, `bootctl(1)`, `ukify(1)`
