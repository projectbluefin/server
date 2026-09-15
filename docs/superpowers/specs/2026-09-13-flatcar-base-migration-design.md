# Flatcar Version Parity Design

**Status:** Proposed design

## Purpose

This project is an experiment with a concrete question: **what would Flatcar
Container Linux look like if it were built with BuildStream?**

Flatcar is a Gentoo/portage cross-build driven by its own SDK. Bluefin Server
builds with `bst`. The question is not academic - it decides whether an
image-based server OS of Flatcar's shape can be produced by a declarative,
cache-backed build graph instead of a distribution toolchain, and what is lost
or gained on the way.

The target is **version parity, not ABI parity.**

- **Version parity** means: for each component Flatcar ships, Bluefin Server
  builds the same upstream version from source in BuildStream. systemd 257
  means systemd 257. Kernel `6.12.102` means kernel `6.12.102`.
- **ABI parity is explicitly not the goal.** Flatcar's binaries come from
  `x86_64-cros-linux-gnu-gcc (Gentoo Hardened 14.3.1_p20250801 p4)` with their
  patch set; ours will not. The binaries will differ, and that is expected and
  accepted. Where a difference in behavior falls out of a difference in
  toolchain, that difference is a finding worth recording, not a defect to
  paper over.

The distinction matters because it sets what "done" means. Done is not "our
bytes match theirs". Done is "we build the versions Flatcar builds, the result
boots and behaves, and we can say precisely where a BuildStream-built Flatcar
diverges from the real one."

**The build base stays freedesktop-sdk 26.08.** Hard rule 1 is unchanged:
compose from FSDK `components/*`. Version parity is pursued *within* the FSDK
graph, by building the versions Flatcar ships rather than by importing
Flatcar's tree wholesale. Where FSDK's pinned version of a component differs
from Flatcar's, closing that difference is the parity work.

## Problem

Bluefin Server currently composes its OS payload from two incompatible
software domains:

- Userspace from freedesktop-sdk 26.08 (`components/*`): systemd 261, glibc
  from the FSDK bootstrap, `uutils-coreutils`, `openssh-systemd`, `podman`,
  `xfsprogs`, `gnupg`.
- Kernel and out-of-tree modules from Flatcar stable 4593.2.5
  (`flatcar/flatcar-kernel.bst`, `flatcar/flatcar-zfs.bst`): kernel
  `6.12.102-flatcar`, ZFS built against that kernel, both shipped as prebuilt
  binaries.

Every defect class hit during installer bring-up came from the seam between
those two domains, not from either domain individually:

- The installer builds the *target* OS initrd with FSDK `dracut` against the
  Flatcar module tree (`elements/oci/bluefin-server-installer.bst`, step 1b,
  `--kmoddir /target-root/usr/lib/modules/${TARGET_KVER}`). Flatcar nests its
  modules at `usr/lib/modules/6.12.102-flatcar/6.12.102-flatcar/`, which FSDK
  tooling does not expect, and storage drivers silently went missing from the
  initrd.
- USB and SCSI storage drivers had to be force-loaded and `udevadm settle`
  polled by hand before `systemd-sysinstall` would see the target disk.
- `os-release-flatcar.bst` already lies about identity (`ID=flatcar`,
  `CPE_NAME=cpe:/o:flatcar-linux:...`) purely so Flatcar sysexts will attach to
  an FSDK userspace. The sysext compatibility check passes on a fiction.

The repository therefore maintains a permanent ABI straddle to obtain one
thing: a long-term-support kernel with a matching, prebuilt ZFS module.

## Goals

- Achieve version parity with Flatcar 4593.2.5: build each component Flatcar
  ships at the version Flatcar ships it, from source, in BuildStream.
- Keep BuildStream as the only build system and the DDI/installer contract
  unchanged.
- Keep the installer `systemd-sysinstall`-native and `systemd-repart`-based.
- Conform to Flatcar's boot contract and partition layout, so a
  BuildStream-built payload is substitutable for the real one.
- Delete the hand-written initrd repair path.
- Record every divergence between the BuildStream build and upstream, with
  evidence, as the primary output of the experiment.
- Make `ID=flatcar` true rather than cosmetic.

## Non-goals

- **ABI or byte-level parity with Flatcar's binaries.** Different toolchain,
  different binaries. See "Purpose".
- Reproducing Flatcar's build system. `coreos-assembler`, the Flatcar SDK, and
  portage stay out of the tree; `bst` is the point of the exercise.
- Matching Flatcar's full package set. Parity is scoped to the components
  Flatcar publishes versions for.
- Adopting Flatcar's update stack (`update_engine`, `locksmithd`) or its
  provisioning stack (Ignition, `coreos-cloudinit`). Bluefin Server stays on
  `systemd-sysupdate` plus Kured with `systemd-creds`.
- Changing the k0s delivery model. k0s stays an optional sysext; the
  KubeStellar console path depends on it.
- arm64 support. Flatcar publishes `arm64-usr`; that is follow-on work.

## Method: import first, then substitute

Version parity needs an oracle. Building a component and asking "is this
right?" is unanswerable without something known-good to compare against.

So the work runs in two movements:

1. **Import.** Bring Flatcar's own binaries in as pinned, digest-verified
   artifacts and boot them on Bluefin Server's installer and partition layout.
   This establishes a known-good baseline and forces every interface question -
   boot contract, partition types, cmdline, verity offsets - into the open
   before any compiler runs. The "Boot proof" section below records this
   baseline already achieved.
2. **Substitute.** Replace imported binaries with BuildStream-built ones at the
   same versions, one component at a time, re-running the same boot proof after
   each swap. A component is at parity when the image still boots and behaves
   with it built rather than imported.

The imported base is scaffolding with a purpose: it is the control against
which each BuildStream-built component is measured. It is not the destination.

## Upstream artifact survey

Measured against `https://stable.release.flatcar-linux.net/amd64-usr/4593.2.5/`
on 2026-09-13. Every artifact carries `.DIGESTS`, `.DIGESTS.asc`, and `.sig`
companions, so each import can be pinned by sha256 in `bst` and independently
GPG-verified at release time.

| Artifact | Size | Contents |
|---|---|---|
| `flatcar-container.tar.gz` | 377 MiB | Complete OS tree: `/usr` (19,658 entries), `/boot`, `/oem` |
| `flatcar_production_image_sysext.squashfs` | 418 MiB | The same `/usr`, packaged as a verity-capable sysext squashfs |
| `flatcar_production_image.vmlinuz` | 32 MiB, in use today | Kernel `6.12.102-flatcar` **with a two-stage initramfs compiled in** (`CONFIG_INITRAMFS_SOURCE="bootengine.cpio"`) |
| `flatcar_production_pxe.vmlinuz` | 32 MiB | Byte-for-byte the same size as the above; same kernel, same embedded initramfs |
| `flatcar_production_pxe_image.cpio.gz` | 374 MiB | Four cpio entries wrapping `usr.squashfs`; a RAM-boot OS payload, **not** a driver initrd |
| `flatcar_production_image_initrd_contents.txt` / `_realinitrd_contents.txt` | text | Per-stage manifests for the embedded initramfs: 339 and 2,280 entries |
| `usr/lib/flatcar/bootengine.img` (inside the tarball) | 50 MiB | Stage 2 of that initramfs, standalone: squashfs, 2,280 entries, `/init` + `/etc/initrd-release` |
| `flatcar-zfs.raw` | 3 MiB | ZFS sysext (in use today) |
| `flatcar-podman.raw` | 33 MiB | Podman sysext |
| `rootfs-included-sysexts/containerd-flatcar.raw` | 24 MiB | containerd sysext |
| `rootfs-included-sysexts/docker-flatcar.raw` | 54 MiB | Docker sysext |
| `flatcar_production_image_packages.txt`, `_contents.txt`, SBOM | text | Package manifest and provenance |
| `version.txt` | text | `FLATCAR_VERSION=4593.2.5`, `FLATCAR_BUILD_ID="2026-08-11-2350"` |

Verified contents of `flatcar-container.tar.gz`:

- systemd 257 (`usr/lib/systemd/libsystemd-shared-257.so`).
- glibc 2.41 (`usr/lib64/glibc-2.41/`).
- Everything the current design depends on is present: `systemd-repart`,
  `systemd-sysext`, `systemd-confext`, `systemd-sysupdate`, `systemd-creds`,
  `bootctl`, `machinectl`, `systemd-nspawn`, `bash`, `sshd`, `crictl`.
- Flatcar's own stack that must be masked or stripped: `update_engine`,
  `update_engine_client`, `locksmithd`, `ignition`, `coreos-cloudinit`,
  `flatcar-update`, `download_sysext`, `ensure-sysext.service`.
- `systemd-sysinstall` is **absent** — it is an FSDK 261 tool.

## Design

### The installer and the payload diverge in version, not in base

Both images are composed from FSDK 26.08. They differ in which versions they
pin.

- **Installer** tracks FSDK's own versions, including systemd 261. It is the
  only consumer of `systemd-sysinstall`, which does not exist in systemd 257,
  so it cannot follow the payload down to Flatcar's version. Hard rule 3 is
  preserved untouched.
- **Installed OS payload** tracks Flatcar's versions - systemd 257 and the rest
  of the parity matrix - still built from FSDK `components/*`.

This split is safe because the installer's contract with the DDI is
byte-level, not content-level: `files/installer/repart.d/20-root.conf` copies
the DDI into the root partition with `CopyBlocks=`. Nothing in the installer
inspects the payload's userspace. Changing what is inside the XFS image does
not change how it is written.

### New element: `flatcar/flatcar-usr.bst`

`kind: manual`, mirroring the existing `flatcar-zfs.bst` import pattern:

- `sources:` one `kind: remote` entry for
  `flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-container.tar.gz`,
  pinned by `ref:` sha256, using the existing `flatcar:` alias in
  `include/aliases.yml`.
- `variables: strip-binaries: ""` (prebuilt binaries; the FSDK stripper must
  not touch them).
- `install-commands:` extract `./usr` into `%{install-root}/usr`, then remove
  the update and provisioning stack listed above, and flatten Flatcar's nested
  module directory to the single-level layout the rest of the tree expects.

Removals are explicit `rm` lines with a comment naming the replacement, not a
wildcard sweep, so a future Flatcar bump that renames a unit fails loudly.

### Overlay: what Bluefin keeps

These elements are OS policy, not upstream software, and carry over unchanged:

`os-release-flatcar.bst` (now truthful), `os-sysupdate.bst`,
`os-k0s-sysupdate.bst`, `os-sysupdate-keys.bst`, `os-networkd.bst`,
`os-k0s-first-boot.bst`, `os-creds-prov.bst`, `os-kured-hook.bst`,
`os-justfile.bst`, `os-issue.bst`, `os-image-info.bst`, `os-countme.bst`,
`os-sshd-preset.bst`, `os-sshd-config.bst`.

### Overlay: what Flatcar displaces

Removed from the OS payload once the Flatcar base lands:

| Current element | Replacement |
|---|---|
| `freedesktop-sdk.bst:public-stacks/runtime-minimal.bst` | Flatcar `/usr` |
| `freedesktop-sdk.bst:components/systemd.bst` | Flatcar systemd 257 |
| `freedesktop-sdk.bst:components/dbus.bst`, `dbus-broker.bst`, `kmod.bst`, `shadow.bst` | Flatcar `/usr` |
| `freedesktop-sdk.bst:bootstrap/bash.bst` | Flatcar `/usr/bin/bash` |
| `bluefin-server/uutils-coreutils.bst` | Flatcar coreutils |
| `freedesktop-sdk.bst:components/openssh-systemd.bst` | Flatcar `/usr/bin/sshd` |
| `freedesktop-sdk.bst:components/podman.bst` | `flatcar-podman.raw` sysext |
| `freedesktop-sdk.bst:components/xfsprogs.bst`, `gnupg.bst`, `ca-certificates.bst`, `tzdata.bst` | Flatcar `/usr` |
| `bluefin-server/linux-firmware-split.bst` | Flatcar firmware in `/usr/lib/firmware` |

Moving Podman from the base DDI to a sysext also brings the tree into line
with hard rule 4, which already forbids container runtimes in the base DDI.

### Initrd: the kernel already has one

The FSDK `dracut` invocation for the target OS initrd is deleted, and nothing
replaces it. The kernel this repository already imports ships a complete,
two-stage initramfs compiled in.

`flatcar_production_image_kernel_config.txt` for this release states it
directly:

```
CONFIG_BLK_DEV_INITRD=y
CONFIG_INITRAMFS_SOURCE="bootengine.cpio"
CONFIG_INITRAMFS_COMPRESSION_XZ=y
```

Flatcar publishes a manifest for each stage:

| Stage | Manifest | Entries | Contents |
|---|---|---|---|
| 1 | `flatcar_production_image_initrd_contents.txt` | 339 | `rootfs-0/` shim: a 6,772-byte `/init`, busybox, `kmod`, `dmsetup`, `veritysetup`, and empty `/realinit` + `/sysusr/usr` mount points |
| 2 | `flatcar_production_image_realinitrd_contents.txt` | 2,280 | The systemd initrd - byte-identical entry count to `/usr/lib/flatcar/bootengine.img` |

Stage 1 is a busybox shim. It is the only stage compiled into the kernel; the
`realinit` entry in its cpio is an empty directory. Stage 2 is
`bootengine.img`, a 50 MiB squashfs built by `sys-kernel/bootengine` 0.0.38-r40
from Flatcar's dracut module set, carrying `/init`, `/etc/initrd-release`, and
`/etc/cmdline.d/10-default.conf`. Stage 1 loop-mounts it **from the `/usr` it
just mounted**, so stage 2 versions with the OS payload automatically rather
than with the kernel. It conforms to the systemd initrd interface exactly as
`docs/INITRD_INTERFACE.md` prescribes.

`flatcar_production_image.vmlinuz` and `flatcar_production_pxe.vmlinuz` are
both 34,245,760 bytes: one kernel, one embedded stage 1, two names.

The consequence is that `elements/flatcar/flatcar-kernel.bst` has been
importing a self-sufficient kernel all along, and the installer has been
building a second initrd to lay on top of it.

`flatcar_production_pxe_image.cpio.gz` is not a driver initrd. It is a
four-entry cpio whose payload is `usr.squashfs` at 374 MiB, and stage 1 has an
explicit branch for it: when no `/usr` partition is found and `/usr.squashfs`
exists in the initramfs, that file becomes `/usr` with `usrfstype=squashfs`.
It is the PXE path, not the disk path.

### Verified by experiment

The claim above is not inferred from the kernel config alone. Booting the
pinned kernel in QEMU with **no `-initrd` argument and no disk attached**:

```
qemu-system-x86_64 -enable-kvm -m 2048 -cpu host -nographic -no-reboot \
  -kernel <cached flatcar_production_image.vmlinuz> \
  -append "console=ttyS0,115200n8 root=LABEL=ROOT usr=PARTLABEL=USR-A"
```

produced:

```
[    0.000000] Linux version 6.12.102-flatcar (build@pony-truck.infra.kinvolk.io) ...
[    0.025767] Kernel command line: rootflags=rw mount.usrflags=ro console=ttyS0,115200n8 root=LABEL=ROOT usr=PARTLABEL=USR-A
[    1.053101] Run /init as init process
[    1.171015] SCSI subsystem initialized
...
Waiting for drive...
Still waiting for drive...
```

Three facts fall out of those six lines:

- `Run /init as init process` with no initrd supplied proves the initramfs is
  compiled in and live, not merely declared in the config.
- Stage 1 loaded storage modules and then blocked on `Waiting for drive...`,
  which is the busybox shim hunting for `usr=PARTLABEL=USR-A`. With no disk
  attached it waits forever. That message is the boot contract asserting
  itself.
- `rootflags=rw mount.usrflags=ro` appears **before** the appended arguments:
  the kernel carries a built-in `CONFIG_CMDLINE` that any UKI cmdline is
  merged with, not a replacement for.

### The boot contract: decided, conform to it

**Decision: follow Flatcar's design.** The OS payload becomes a `/usr` image on
a verity-protected A/B partition pair, and `/` becomes writable state. The
alternatives - overriding the built-in initramfs, or generating one with
`mkosi-initrd` - are dropped.

The contract is not guesswork. Stage 1's `/init` was extracted from the kernel
and read directly; it is 6,772 bytes of shell and the relevant logic is exact:

```sh
verityusr=$(cmdline_arg verity.usr)
usrhash=$(cmdline_arg verity.usrhash)
verityusr=$(find_drive "${verityusr}")
if echo "${verityusr}" | grep -q "^/" && [ "${usrhash}" != "" ]; then
  veritysetup --panic-on-corruption --hash-offset=1065345024 open "${verityusr}" usr "${verityusr}" "${usrhash}"
  status=$(dmsetup status usr | cut -d " " -f 4)
  [ "${status}" = V ] || { echo "Verity setup failed" >&2; false; }
fi
usr=$(cmdline_arg mount.usr $(cmdline_arg usr))
usrfstype=$(cmdline_arg mount.usrfstype $(cmdline_arg usrfstype auto))
usrflags=$(cmdline_arg mount.usrflags $(cmdline_arg usrflags ro))
mount -t "${usrfstype}" -o "${usrflags}" "${usr}" /sysusr/usr
losetup -r "${LOOP}" /sysusr/usr/lib/flatcar/bootengine.img
mount -t squashfs "${LOOP}" /underlay
mount -t overlay -o rw,lowerdir=/underlay,upperdir=/work/realinit,workdir=/work/work overlay /realinit
mount -o move /sysusr/usr /realinit/sysusr/usr
exec switch_root /realinit /init
```

Seven consequences, each load-bearing:

1. **Verity is one partition, not two.** `--hash-offset=1065345024` is
   hardcoded, with the comment "Hardcoded expected value from the image GPT
   layout". The filesystem occupies the first 1,065,345,024 bytes and the
   verity hash tree follows it in the same partition. This is incompatible with
   `systemd-repart`'s `Verity=data` / `Verity=hash` two-partition model, so the
   image is built with the hash appended by the DDI element and `repart` simply
   `CopyBlocks=` the result - the existing contract, unchanged.
2. **Our `/usr` must fit in 1,065,345,024 bytes.** Flatcar's own uses 454 MiB of
   it. This is a hard build-time budget, and the DDI element must fail loudly
   when exceeded rather than silently corrupt the hash offset.
3. **Verity is optional.** The block is guarded by
   `[ "${usrhash}" != "" ]`. Landing the partition layout without verity is a
   valid intermediate state, so layout and verity split cleanly into two
   tickets.
4. **The root hash must reach the kernel cmdline** as `verity.usrhash=`.
   Flatcar publishes theirs per release in
   `flatcar_production_image_verity.txt`
   (`20b08968dc4527a622b7f9f0ba9b6e1a16377500f1f9f93231712ccb45150570`). Ours is
   an output of our own DDI build, baked into the UKI cmdline by `ukify`. That
   binds each UKI to exactly one `/usr` image, which is precisely the property
   A/B updates need.
5. **The `/usr` filesystem stays XFS.** `mount -t "${usrfstype}"` passes the
   type through, so `mount.usrfstype=xfs` works. Only `auto` and `btrfs` get
   Flatcar's `rescue=nologreplay` special-casing.
6. **`/usr/lib/flatcar/bootengine.img` must survive the import.** Stage 1
   loop-mounts it from the mounted `/usr`; without it the boot stops between
   stages. It is an explicit keep in the `flatcar-usr.bst` strip list, not an
   incidental leftover.
7. **Ignition needs no masking.** Measured, not assumed: on a disk with no
   Ignition config, stage 2 runs `ignition-setup-pre.service` to completion,
   skips `ignition-delete-config.service` ("no trigger condition checks were
   met"), and reaches `ignition-subsequent.target - Subsequent (Not Ignition)
   boot complete`. The state machine degrades to a no-op on its own. Masking
   is available if a future unit misbehaves, but it is not a prerequisite.

### Target partition layout

Flatcar's own GPT, read from `flatcar_production_image.bin`:

| # | PARTLABEL | MiB | Type GUID |
|---|---|---|---|
| 1 | `EFI-SYSTEM` | 1024 | `c12a7328-f81f-11d2-ba4b-00a0c93ec93b` |
| 2 | `BIOS-BOOT` | 2 | `21686148-6449-6e6f-744e-656564454649` |
| 3 | `USR-A` | 2048 | `5dfbf5f4-2848-4bac-aa5e-0d9a20b745a6` |
| 4 | `USR-B` | 2048 | `5dfbf5f4-2848-4bac-aa5e-0d9a20b745a6` |
| 6 | `OEM` | 1024 | `0fc63daf-8483-4772-8e79-3d69d8477de4` |
| 7 | `OEM-CONFIG` | 64 | `c95dc21a-df0e-4340-8d7b-26cbfa9a03e0` |
| 9 | `ROOT` | 1784 | `3884dd41-8582-4404-b9a8-e9b84f2df50e` |

Partitions 5 and 8 are absent; the numbering is ChromeOS heritage.

What Bluefin Server adopts, as `repart.d` drop-ins replacing the current
`10-esp.conf` / `20-root-a.conf` / `30-var.conf`:

| PARTLABEL | Type | Source | Notes |
|---|---|---|---|
| `EFI-SYSTEM` | ESP, vfat | `bootctl install` + UKI | Carries the UKI whose cmdline pins `verity.usrhash=` |
| `USR-A` | `5dfbf5f4-…` | `CopyBlocks=` the `/usr` DDI | Read-only, verity, 2048 MiB |
| `USR-B` | `5dfbf5f4-…` | empty | The A/B slot `50-root.transfer` already names but the installer never provisioned |
| `OEM` | `0fc63daf-…` | `Format=ext4`, `Label=OEM` | Required: stage 2 waits on `dev-disk-by-label-OEM.device` |
| `ROOT` | `3884dd41-…` | `Format=`, `GrowFileSystem=yes` | Writable state |

`BIOS-BOOT` is dropped: this is a UEFI-only image, per hard rule 5.
`OEM` is **required**, not optional. Stage 2 declares a dependency on
`dev-disk-by-label-OEM.device`; without it the boot waits 90 seconds and drops
to an emergency shell. Note the match is on **filesystem label** `OEM`, not
partition label, so the partition must be formatted with `mke2fs -L OEM` or
equivalent. `OEM-CONFIG` is dropped: nothing in the boot path references it.

This closes the known gap recorded as an `xfail` in
`tests/unit/test_repart_layout.py`, where `50-root.transfer` names both slots
but the installer provisions only one. Roadmap items 1, 2, and 3 - A/B slots,
read-only `/usr`, dm-verity - arrive as a consequence of conforming rather than
as three separate projects.

### Boot proof

The adopted design was booted end to end before any Bluefin code was written,
using only upstream artifacts and unprivileged tooling (`mksquashfs`,
`mke2fs -d`, `sfdisk`; no root, no loop mounts).

A 10 GiB GPT was built with Flatcar's type GUIDs: `EFI-SYSTEM`, `USR-A`,
`USR-B`, `OEM`, `ROOT`. Flatcar's `/usr` tree was packed with `mksquashfs`
(356 MiB, against the 1,065,345,024-byte budget) and written into `USR-A`;
`OEM` and `ROOT` were `mke2fs -d` ext4 images. The pinned kernel was booted
with no external initrd:

```
-append "console=ttyS0,115200n8 mount.usr=PARTLABEL=USR-A \
         mount.usrfstype=squashfs mount.usrflags=ro root=PARTLABEL=ROOT rootfstype=ext4"
```

The full chain ran:

```
[    1.122448] Run /init as init process
Mounting /usr from /dev/vda2
[    1.776610] systemd[1]: Successfully made /usr/ read-only.
[    1.788585] systemd[1]: systemd 257.9 running in system mode
[    1.794580] systemd[1]: Running in initrd.
[    4.133550] systemd[1]: Switching root.
Welcome to Flatcar Container Linux by Kinvolk 4593.2.5 (Oklo)!
[  OK  ] Reached target multi-user.target - Multi-User System.
localhost login:
```

SSH host keys were generated and DHCP brought `ens3` up on `10.0.2.15`. Every
claim in this section - `PARTLABEL` resolution, read-only `/usr`,
`bootengine.img` loop-mount, `switch_root`, Ignition degrading to a no-op - is
from that trace rather than from reading upstream code.

Two corrections came out of it, both folded in above: `OEM` is required, and
Ignition needs no masking.

### Versioning

**Use Flatcar's version.** `release-version` is the Flatcar release the image
targets, verbatim:

```
4593.2.5
```

Not a composite, not a translation. If the image claims parity with Flatcar
4593.2.5, it says `4593.2.5`.

This is already half-true in the tree. `os-release-flatcar.bst` sets
`VERSION_ID=${FLATCAR_VERSION}` and `CPE_NAME=cpe:/o:flatcar-linux:flatcar_linux:${FLATCAR_VERSION}`
while `PRETTY_NAME` carries the unrelated `%{release-version}`. One image
currently answers two different questions about what version it is. Adopting
Flatcar's version collapses them.

It also makes the sysext story honest. Flatcar's `systemd-sysext` images match
on `ID` and `VERSION_ID`; `flatcar-zfs.raw` attaches today only because
`os-release-flatcar.bst` already asserts Flatcar's identity. With
`release-version` equal to the Flatcar version, `flatcar-podman.raw`,
`containerd-flatcar.raw`, and the rest attach on a true statement rather than
a convenient one.

Consequences:

- `.github/scripts/check-release-version.py` inverts. It stops enforcing
  `release-version` against the FSDK junction ref and starts enforcing it
  against `flatcar-version` in `include/flatcar.yml`.
- The FSDK pin does not disappear, it stops being user-facing. It remains in
  the junction ref and in `fsdk_ref` for provenance, and is recorded in
  `os-release` as its own field rather than smuggled into the version string.
- Artifact names follow: `bluefin-server-ddi-4593.2.5.raw.zst`.
- Prerelease suffixes keep working. `check-release-version.py` already allows
  them, so an alpha is `4593.2.5-alpha.1`.

This supersedes both earlier proposals: the two-field split and the
`26.08.XX.$FLATCARVERSION` composite.

## The version-parity plan, folded in

A competing plan proposed version parity directly. It is now the frame of this
document rather than an alternative to it. What it contributes:

Adopted as the frame:

- **Version parity as the objective**, with feature parity as a side effect
  rather than the target. See "Purpose".
- **Build the matched versions from source in BuildStream**, on the FSDK base.
- **Single source of truth for pins.** Extend `include/flatcar.yml` to carry
  every pinned upstream version, with a single-consumer rule so no element or
  script hardcodes one.
- **Provisioning parity via `systemd-creds`**, covering SSH keys, networkd
  configuration, `systemd-firstboot`, and TPM2 sealing, in preference to
  Ignition. Both plans agree here.
- **Reboot coordination for non-Kubernetes hosts**, matching roadmap item 6.

Clarified:

- **Version parity is not ABI parity, and does not aim to be.** Flatcar's
  kernel banner reads
  `x86_64-cros-linux-gnu-gcc (Gentoo Hardened 14.3.1_p20250801 p4)`; building
  the same version under the FSDK toolchain produces different binaries. That
  is accepted. The measure of success is that the image boots and behaves,
  and that each divergence is recorded - not that bytes match.

Amended by measurement:

- **A/B is `USR-A`/`USR-B`, not `root-a`/`root-b`.** Flatcar's pair uses type
  GUID `5dfbf5f4-2848-4bac-aa5e-0d9a20b745a6`, with `/` as writable state.
  Mirroring a whole-rootfs DDI into a second slot does not satisfy the
  initramfs contract.
- **Read-only `/usr` needs no fstab or cmdline `ro` work.** `mount.usrflags=ro`
  alone produced `Successfully made /usr/ read-only` in the boot trace.
- **A kernel built from a plain upstream tarball has no embedded initramfs.**
  The boot proof depends on `CONFIG_INITRAMFS_SOURCE="bootengine.cpio"`, so any
  BuildStream-built kernel must also build a `bootengine.cpio` equivalent and
  set that config, or supply an external initrd. This is a concrete parity
  requirement, and it multiplies per additional kernel.

Deferred:

- **Three kernels (LTS, Fedora CoreOS, Ubuntu).** No published Flatcar release
  has an Ubuntu-based build, so there is no upstream version to match for that
  third kernel. Revisit once single-kernel parity holds.
- **Replacing the k0s sysext with a Flatcar `k8s` sysext.** That plan's own
  risk table concedes the Flatcar sysext is "binaries-only, not a full control
  plane" and that dropping k0s "removes the single-node k8s story". The
  KubeStellar console path depends on it.

## Rejected alternatives

- **Replacing the FSDK base with Flatcar's `/usr` tree.** Rejected: the build
  base stays freedesktop-sdk 26.08 and hard rule 1 is unchanged. Flatcar's
  binaries are imported as a *reference* to boot against and measure, not as
  the shipped payload. See "Method: import first, then substitute".
- **Reproducing Flatcar's build system** - the Flatcar SDK, portage, or
  `coreos-assembler`. Rejected: building with `bst` is the point of the
  experiment. Matching Flatcar's *versions* under FSDK is the work; matching
  their toolchain would answer a different question.
- **Status quo drift.** Rejected: leaving component versions wherever FSDK
  happens to pin them means no parity claim can be made, and
  `os-release-flatcar.bst` keeps asserting `ID=flatcar` on a fiction.
- **Boot Flatcar's `/usr` with dm-verity, as upstream does.** **Adopted.** Not
  a follow-on and not optional: stage 1 hardcodes
  `--hash-offset=1065345024` and expects `verity.usr=` / `verity.usrhash=`, so
  this is simply how the embedded initramfs boots. See "The boot contract:
  decided, conform to it".
- **Override the built-in initramfs with a generated one**, via dracut or
  `mkosi-initrd --generic`. Rejected: it is what the repository does today and
  what this design exists to stop. Keeping it means owning an initrd generator
  and a foreign module tree forever.

## Migration phases

Each phase is independently landable and independently verifiable. Hard rule 1
is untouched throughout: the base stays FSDK 26.08.

1. **Invariants.** Adopt Flatcar's version as `release-version` and invert
   `check-release-version.py` to enforce it against `include/flatcar.yml`.
   Extend that file to the single source of truth for pins. Record this design
   as an ADR.
2. **Version audit.** Inventory the component versions Flatcar 4593.2.5 ships,
   from `flatcar_production_image_packages.txt` and the SBOM, and diff them
   against what FSDK 26.08 pins. The output is a parity matrix: component,
   Flatcar version, FSDK version, gap. This decides the order of every phase
   after it, and nothing downstream should start before it exists.
3. **Reference import.** Bring Flatcar's binaries in as pinned artifacts to
   boot against, per "Method: import first, then substitute". They are the
   oracle, not the payload. Contract tests assert
   `/usr/lib/flatcar/bootengine.img` is present and the module layout is flat.
4. **Partition layout.** Replace `repart.d/10-esp.conf`, `20-root-a.conf`, and
   `30-var.conf` with `EFI-SYSTEM` / `USR-A` / `USR-B` / `OEM` / `ROOT` using
   upstream type GUIDs. Verity stays off here, which stage 1 explicitly
   permits, so the layout is provable on its own.
5. **`/usr` payload.** The OS payload becomes a `/usr` image sized to the
   1,065,345,024-byte budget with the verity hash tree appended, and its root
   hash baked into the UKI cmdline as `verity.usrhash=`.
6. **Substitution.** Working down the parity matrix, replace each imported
   binary with an FSDK-built component at Flatcar's version, re-running the
   boot proof after each swap. Record every behavioral divergence.
7. **Boot proof in CI.** `just show-me-the-future` installs and boots; the Lima
   end-to-end test drives the KubeStellar console login against the result.
8. **Follow-on.** Wire `50-root.transfer` to the real `USR-A`/`USR-B` slots and
   retire the `xfail` in `tests/unit/test_repart_layout.py`; arm64.

## Verification

- `just validate` after every element change.
- `python3 .github/scripts/docs-checks.py`.
- `pytest tests/unit` including new contract tests for the import elements.
- `just cluster-build` on the ghost cluster for heavy builds.
- `just show-me-the-future` QEMU install-and-boot smoke test.
- `just test-e2e-lima` for the console login path.

## See also

- [docs/skills/gap-analysis-distros.md](../../skills/gap-analysis-distros.md) - distro comparison that framed this.
- [docs/skills/architecture-roadmap.md](../../skills/architecture-roadmap.md) - A/B slots and verity follow-on.
- [docs/skills/ddi-installer.md](../../skills/ddi-installer.md) - installer and DDI contract.
