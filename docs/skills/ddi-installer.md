---
name: ddi-installer
description: Use when building or debugging the Bluefin Server DDI live installer, or managing the systemd-sysinstall recipes or target boot configurations.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-26"
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---
# DDI Installer

## When to Use

- Building or debugging the Bluefin Server live installer media.
- Writing or refining `systemd-repart`, `bootctl`, or `ukify` configurations.
- Packaging or publishing DDI assets to GitHub Releases.
- Managing partition recipes for the target disk layout (`10-esp.conf`,
  `20-root-a.conf`, `30-var.conf`).

## When NOT to Use

- OCI-only image work (no installer involvement).
- Bootc-specific changes.
- Desktop or nspawn machine image work.

## Architecture

The installer is systemd-native and offline by default. The OS DDI payload
(`bluefin-server-ddi.bst`) is embedded as a data partition on installer media
at build time; no network access is required for the default install. PXE/
netboot clients may opt into downloading the DDI over the LAN instead (see
"PXE network installs" below), but the embedded path stays the default.

The installer UI is systemd's built-in `systemd-sysinstall` which provides a
terminal-based interactive installation that:

- Prompts for the target disk (selected interactively or on the command line).
- Validates target disk size and suitability.
- Offers to erase the target disk or install alongside existing partitions.
- Copies the OS filesystem DDI block-for-block using `systemd-repart` and
  partition recipes (`CopyBlocks=`).
- Registers the bootloader (`systemd-boot`) and the Unified Kernel Image (UKI)
  using `bootctl`.
- Propagates installer environment settings (locale, keymap, timezone) to the
  target OS via encrypted credentials.
- Reboots into the installed system.

User provisioning is handled on the target system's first boot via systemd
system credentials so the base image remains stateless. `systemd-sysusers`
consumes root account records, `systemd-tmpfiles` consumes `tmpfiles.extra`
for arbitrary first-boot files, and `systemd-network-generator` consumes
`network.conf.*` / `network.link.*` / `network.netdev.*` /
`network.network.*` credentials before networkd starts. The stock interactive
`systemd-firstboot.service` stays masked, but
`bluefin-firstboot-credentials.service` runs `systemd-firstboot`
non-interactively when `firstboot.locale`, `firstboot.timezone`,
`firstboot.hostname`, or related credentials are present. When
`firstboot.hostname` is supplied, the service also applies the live kernel
hostname before `systemd-networkd` starts so first-boot DHCP uses it. With no
credentials, the target keeps the default DHCP network and does not prompt. The
target DDI
also pre-stages the extracted CA certificate bundle
(`/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem` and
`/etc/ssl/certs/ca-certificates.crt`) and a standard `/etc/hosts` file for
container runtime pod sandboxes.

## Core Process

1. Keep the live media thin; orchestrate install-time flow with native systemd
   utilities.
2. The live environment boots with `systemd.unit=system-install.target` as a
   kernel command-line option.
3. systemd isolates `system-install.target` and starts
   `systemd-sysinstall.service` on `/dev/tty0`. Pinning `TTYPath` keeps the
   interactive TUI on the attached display while boot diagnostics remain
   available on the serial console.
4. The live image overrides that service to run `/usr/bin/bluefin-sysinstall`,
   which calls `systemd-sysinstall` with the target OS UKI at
   `/usr/lib/bluefin-server/bluefin-server.efi` so `bootctl link` installs the
   target UKI instead of the installer UKI.
5. `systemd-sysinstall` reads partition recipes from
   `/usr/lib/repart.sysinstall.d/` if it is populated; otherwise it falls back
   to `/usr/lib/repart.d/`. The target recipes are staged at
   `/usr/lib/repart.d/` (`10-esp.conf`, `20-root-a.conf`, `30-var.conf`).
6. `20-root-a.conf` copies the DDI block-for-block from
   `/dev/disk/by-partlabel/bluefin-installer-data` (the embedded DDI data
   partition on the installer media).
7. The immutable root DDI is copied without filesystem growth; `/var` uses
   `GrowFileSystem=yes` to fill the remaining target disk.

## Partition Layout

### Installer media (the USB/raw disk image)

| Partition | Type | Size | Contents |
|---|---|---|---|
| ESP | vfat | 1 GiB fixed | `EFI/BOOT/BOOTX64.EFI` + `EFI/Linux/installer.efi` (UKI) |
| `bluefin-installer-data` | XFS | auto | OS filesystem DDI image, copied block-for-block |

### Target disk (after install)

| Partition | Type | Size | Contents |
|---|---|---|---|
| ESP | vfat | 500 MiB – 1 GiB | `systemd-boot` + target OS UKI (`bluefin-server.efi`) |
| `bluefin-server-root-a` | XFS | 4 GiB – 8 GiB | OS root filesystem (copied from installer data partition) |
| `var` | XFS | ≥ 4 GiB | Writable persistent `/var`; grows to fill remaining disk |

## Installer Boot Flow

```text
UEFI reads ESP → BOOTX64.EFI → installer.efi (UKI)
     │
     ▼
systemd PID 1 starts, reaches system-install.target
     │
     ▼
systemd-sysinstall.service
     │
     ▼
bluefin-sysinstall wrapper
     ├─ Read /proc/cmdline for "unattended"
     ├─► [INTERACTIVE Mode]
     └─► [UNATTENDED Mode]
```

The published installer starts the interactive TUI on `/dev/tty0`. Headless
tests add `unattended` to the kernel command line and do not require console
input.

## Initrd Assembly (cpio-native)

`bluefin-server-installer.bst` assembles the live installer media inline. The
critical constraint is that the DDI is decompressed into `/layer` after the cpio
step; otherwise it would make the initrd several gigabytes or larger and
unbootable.

This is the gist of the process:

1. Create `/init` and set `default.target` to `system-install.target`.
2. Pack the early rootfs as newc cpio + gzip.
3. Decompress the DDI into `/layer` after cpio creation.
4. Build the installer UKI from the staged rootfs.
5. Assemble the GPT disk image with an ESP partition and the embedded DDI data
   partition using `systemd-repart`.

## Build and release details

For the detailed build/export/flash/release workflow, see
[ddi-installer-build.md](ddi-installer-build.md).

## PXE boot artifacts

The installer build also publishes standalone PXE inputs:

- `bluefin-server-pxe-vmlinuz-<ver>` — installer kernel.
- `bluefin-server-pxe-initrd-<ver>.cpio.gz` — installer initrd.

Both files are included in the installer artifact `SHA256SUMS`. Unattended PXE
clients can add `unattended` to the installer command line, for example:

```text
systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended
```

The DDI remains on `bluefin-installer-data` for the default embedded install.

## PXE network installs

PXE clients boot the standalone kernel and initrd (published as
`bluefin-server-pxe-vmlinuz-<ver>` and
`bluefin-server-pxe-initrd-<ver>.cpio.gz`) and opt into downloading the DDI
over the LAN with `inst.*` kernel parameters:

- `inst.ddi_url=<https-url>` — download the zstd-compressed DDI instead of the
  embedded installer partition.
- `inst.ddi_sha256=<hex>` — **mandatory** when `inst.ddi_url` is set; verify the
  downloaded DDI before touching the target disk (fail closed if absent).
- `inst.creds_url=<url>` — download a tar archive of first-boot systemd
  credentials (any `curl` scheme; the iPXE example uses plain `http://`) and
  place them in the installed system's ESP at
  `/loader/credentials/`, where `systemd-stub` hands them to the target OS on
  first boot (consumers: [tpm2-credential-sealing.md](tpm2-credential-sealing.md)).
- `inst.creds_sha256=<hex>` — **mandatory** when `inst.creds_url` is set;
  verify the downloaded archive before touching the target disk (fail closed
  if absent).
- `inst.target_disk=/dev/...` — explicit target disk, overriding
  first-writable-disk auto-detection.

Without `inst.ddi_url`, behavior is unchanged and uses the embedded DDI. The
wrapper (`bluefin-sysinstall`) brings up DHCP via `systemd-networkd-wait-online`,
downloads the DDI with `curl` into `/dev/shm/installer/`, verifies it, checks
that the staging tmpfs and `MemAvailable` can hold the decompressed image,
decompresses it with `zstd`, and feeds it into the **native**
`systemd-sysinstall` flow by staging a temporary
`/usr/lib/repart.sysinstall.d/` override whose `20-root-a.conf` `CopyBlocks=`
points at the downloaded image — no custom installer logic. The override is
written with plain Bash line handling: the live initrd contains only what
`installer-stack.bst` and its transitive runtime deps install (Bash, uutils
coreutils, util-linux, kmod, systemd, `grep`, `curl`, `zstd`, `tar` (declared
for the credentials archive), cryptsetup, xfsprogs, dosfstools). `sed` and
`awk` are **not** present. Every external command the wrapper calls is pinned
by the Step 1a tool check in `bluefin-server-installer.bst`, which fails the
build when one is missing.

The credentials archive is an **uncompressed** ustar/pax/gnu tar (the wrapper
checks the `ustar` magic and feeds tar on stdin, so a `.tar.zst`/`.tar.xz` is
rejected rather than transparently decompressed) and flat: at most 64
top-level regular files named `<name>.cred`, where `<name>` matches
`[A-Za-z0-9][A-Za-z0-9._@~-]*` (`~` is systemd's own drop-in namespace,
`systemd.unit-dropin.<unit>~<name>`), each filename at most 250 bytes, each
file at most 1 MiB, the whole archive at most 16 MiB. Names must be unique
even ignoring case — the ESP is vfat, where `a.cred` and `A.cred` are the same
file. The wrapper validates the `tar -tv` listing column by column before
extracting anything (no directories, symlinks, hardlinks, devices or FIFOs; no
path separators, spaces, control characters or leading dashes/dots in names),
cross-checks it against `tar -t`, extracts only the validated names with
`--no-same-owner --no-same-permissions`, pins its copies to `0644` and
re-checks each is a regular file; any violation rejects the whole archive with
the target disk untouched. Trust model: `inst.creds_sha256` arrives on the same
unauthenticated PXE command line as the URL, so the checksum protects against a
compromised or misconfigured file server, not against whoever controls
DHCP/TFTP — they control both. The archive hardening is defence against
operator error and a bad mirror, not a boundary against a hostile netboot
server; secrets belong in TPM2/host-key-sealed credentials.
Each file must be `systemd-creds encrypt`ed with `--name=<name>` matching the
filename — `systemd-stub` stages ESP credentials under
`/run/credentials/@encrypted`, so plaintext files fail with
`status=243/CREDENTIALS`. The null key suffices for non-secret data
(`firstboot.hostname`, `tmpfiles.extra`); use host/TPM2 keys for secrets:

```bash
systemd-creds --with-key=null encrypt --name=firstboot.hostname hostname.txt firstboot.hostname.cred
systemd-creds --with-key=null encrypt --name=tmpfiles.extra tmpfiles.conf tmpfiles.extra.cred
tar -cf <mac>.tar firstboot.hostname.cred tmpfiles.extra.cred
sha256sum <mac>.tar
```

Ordering and guarantees: both downloads are fetched and verified together,
before any disk change, so a bad DDI or credentials download aborts the install
with the target untouched. The credentials are unpacked into
`/dev/shm/installer/credentials/` at that point and copied onto the ESP only
after `systemd-sysinstall` has created it; the wrapper locates the ESP by GPT
partition type (`c12a7328-f81f-11d2-ba4b-00a0c93ec93b`) on the target disk,
mounts it once, writes `/loader/credentials/*.cred` first, syncs, then stages
the best-effort UEFI fallback loader on the same mount and unmounts. If the ESP
cannot be found or mounted while `inst.creds_url` is set, the install fails
rather than leaving the host to boot unconfigured. Without `inst.creds_url`, no
credentials are written.

Example iPXE stanza (the PXE server mirrors the three release assets, verified
against the signed `SHA256SUMS`, plus one per-host credentials archive):

```ipxe
#!ipxe
set base http://pxe-server:8080/data
kernel ${base}/bluefin-server-pxe-vmlinuz-<ver> systemd.unit=system-install.target console=tty0 console=ttyS0,115200 rw unattended inst.ddi_url=${base}/bluefin-server-ddi-<ver>.raw.zst inst.ddi_sha256=<sha256> inst.creds_url=${base}/creds/${mac}.tar inst.creds_sha256=<sha256>
initrd ${base}/bluefin-server-pxe-initrd-<ver>.cpio.gz
boot
```

### Memory requirements

Everything on a PXE client lives in RAM: the live env is a RAM-resident cpio
rootfs, and the DDI is staged in tmpfs under `/dev/shm/installer/`. systemd
PID 1 mounts `/run` as tmpfs with `size=20%` (≈1.6 GiB on an 8 GiB machine),
which is why `/run` cannot hold the DDI; `/dev/shm` is mounted without a size
option and so uses the kernel tmpfs default of 50% of RAM. `zstd --rm` deletes
the compressed download only after a successful decompress, so the staging
tmpfs must hold the compressed **and** the decompressed DDI at once. Before
decompressing, the wrapper compares the raw size recorded in the zstd frame
header (or 5× the compressed size if the header does not carry it, with a
`WARN`) against both the free space `df` reports for `/dev/shm/installer` and
`MemAvailable` from `/proc/meminfo` minus 256 MiB of headroom, and aborts with
`ERROR: not enough RAM-backed temporary space ... (need ~N MiB; tmpfs has M MiB
free, MemAvailable is K MiB ...)` instead of failing mid-write with `ENOSPC` or
being OOM-killed. The `MemAvailable` bound matters because the tmpfs cap alone
is not proof of memory: the rootfs is its own tmpfs, so `df` on `/dev/shm` can
report space the kernel cannot back.

Plan for the check to pass: `MemAvailable` after the download must exceed the
raw DDI size plus 256 MiB, and the 50% `/dev/shm` cap must hold both copies.
For the 26.08.0 Flatcar-based DDI (365 MiB compressed, ≈1.6 GiB raw) 8 GiB is
the tested and recommended size; smaller machines have not been boot-tested.
The embedded (USB) install path does not stage the DDI in RAM and is
unaffected.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash script is simpler." | A bash script cannot run the systemd-native interactive installer TUI. Use `systemd-sysinstall`. |
| "Kernel image is at `/boot/vmlinuz`." | FSDK installs kernels into `/usr/lib/modules/<kver>/vmlinuz`. Toolchains (dracut, ukify, PXE export) must point to `/usr/lib/modules/<kver>/vmlinuz`. |
| "dracut finds glibc libraries automatically." | In FSDK 26.08, glibc libraries live under `/usr/lib/x86_64-linux-gnu`. `dracut-install` requires `/etc/ld.so.conf` to include `/usr/lib/x86_64-linux-gnu` and `ldconfig` to generate `/etc/ld.so.cache` before dracut runs. |
| "Initrd archive tools (gzip, cpio) are in base-stack." | In FSDK 26.08, gzip and cpio are standalone components; elements packing or unpacking initrds must explicitly declare `components/gzip.bst` and `components/cpio.bst` in `build-depends`. |
| "Use knuckle instead." | knuckle is deprecated in favor of native `systemd-sysinstall` (systemd 261+). |
| "Hardcode `root=/dev/vda2` for QEMU." | Bare metal has different device names. Always use PARTUUID. |
| "Pull the DDI from the network at install time." | Network pull is opt-in via `inst.ddi_url`; verification is mandatory and failures abort before any disk change, while the embedded installer media stays the default. |
| "The live initrd has sed/awk like any Linux box." | It does not. The initrd holds only `installer-stack.bst` plus transitive runtime deps (Bash, uutils coreutils, util-linux, kmod, systemd, `grep`, `curl`, `zstd`, `tar`); `sed` and `awk` are absent and fail with `command not found` (exit 127) after the download. Use Bash builtins, or declare the tool in `installer-stack.bst` and add it to the Step 1a build-time tool check. |
| "`/run` can hold the downloaded DDI." | No. systemd mounts `/run` with `size=20%`; the network DDI stages in `/dev/shm/installer/` (kernel tmpfs default, 50% of RAM) and the wrapper checks tmpfs free space and `MemAvailable` before decompressing. See "Memory requirements". |
| "Per-host configuration needs a custom installer step." | `inst.creds_url` is opt-in and only delivers verified `*.cred` files to the ESP `/loader/credentials/`; the installed OS consumes them through stock systemd credential consumers, so no installer logic is added. |
| "Put the DDI in the initrd cpio." | The DDI is ≈1.6 GiB raw (2 GiB+ once sparse space is written out). The initrd cpio step must run before the DDI is placed in `/layer`. |
| "Store the DDI in the ESP (FAT32)." | FAT32 has a 4 GiB per-file limit. Use a separate XFS partition. |
| "Add an 8 GiB minimum size floor to the DDI." | The rootfs is immutable. It never grows in-place. Content + overhead is enough. |

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] No `installer-knuckle.bst` or custom installer service units exist in the
      codebase.
- [ ] UKI boot cmdline points to `systemd.unit=system-install.target`.
- [ ] Serial console `console=ttyS0,115200` is the final console argument in the
      installer UKI cmdline.
- [ ] `installer-stack.bst` explicitly includes XFS and vfat support.
- [ ] `bluefin-server-installer.bst` overrides `systemd-sysinstall.service`
      with `SuccessAction=poweroff`/`FailureAction=poweroff` for clean shutdown.
- [ ] The interactive installer service sets `TTYPath=/dev/tty0` so the TUI
      appears on the attached display even when serial is the primary console.
- [ ] `bluefin-server-installer.bst` decompresses the DDI after the cpio step.
- [ ] `files/installer/repart.d/20-root-a.conf` has `GrowFileSystem=no`.

## See also

- [ddi-installer-build.md](ddi-installer-build.md)
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (OS DDI and Installer terminology).
- `systemd-sysinstall(8)`, `systemd-sysinstall.service(8)`
- `systemd-repart(8)`, `repart.d(5)`
- `bootctl(1)`, `ukify(1)`
- `systemd-growfs(8)`
