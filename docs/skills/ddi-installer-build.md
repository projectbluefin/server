---
name: ddi-installer-build
description: Build, export, and dogfood the Bluefin Server image set (OS DDI, signed UKIs, netboot ESP) and the opt-in sysexts.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-29"
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
---
# Image Build and Dogfood

Use this skill when you need to build the release image set, export it, boot it
in QEMU, or run the end-to-end install/update/rollback test.

## Build targets

The repo exposes the main build entrypoints through `just`. BuildStream runs
inside the FSDK `bst2` container (`just bst`); it is not installed locally.

```bash
just validate          # version invariants + resolve the shipped element graphs
just test-unit         # pytest + bats
just gen-dev-keys      # throwaway Secure Boot + module keys in files/boot-keys/
just set-version V     # set image-version in include/image.yml (<=17 chars,
                       # increasing under strverscmp)
just build-image       # build oci/bluefin-server-image.bst
just export-image      # export the release set to dist/diskless/
just build-sysext      # build oci/k0s-sysext.bst
just export-sysext     # export k0s sysext + SHA256SUMS to dist/sysext/
just build-zfs-sysext  # build oci/zfs-sysext.bst
just export-zfs-sysext # export OpenZFS sysext + SHA256SUMS to dist/sysext/
just build-nvidia-container-toolkit-sysext   # build oci/nvidia-container-toolkit-sysext.bst
just export-nvidia-container-toolkit-sysext  # export NVIDIA Container Toolkit (CDI)
                       # sysext + SHA256SUMS to dist/sysext/
just version / just tags  # FSDK-derived point release and tag set
```

`just export-image` writes one directory per image version containing the OS
DDI, the sysupdate usr/usr-verity sources, both UKIs, the netboot ESP image,
the k0s/KubeStellar/OpenZFS sysext assets, the `efi-keys/` enrollment
payloads, and a `SHA256SUMS` over all of it with its detached signature
`SHA256SUMS.gpg` (signed in-element by `oci/bluefin-server-image.bst`). See
[ddi-installer.md](ddi-installer.md) for what each artifact is.

To publish the set as an OCI artifact (one layer per file, tags `<version>`
and `latest`, artifact type
`application/vnd.projectbluefin.server.release.v1`):

```bash
just publish-oci ghcr.io/<owner>/bluefin-server                 # podman login first
just publish-oci <registry-host>:30500/bluefin-server dist/diskless 1  # plain HTTP
```

## Keys

Every image build signs: the UKIs and systemd-boot with DB, kernel modules
with the module signing certificate, and the release `SHA256SUMS` with the
image signing key. What each key is, where it lives, what `just gen-dev-keys`
generates (throwaway keys in the gitignored `files/boot-keys/`, kept unless
`--force`, a partial set is an error), and how CI supplies the real keys:
[secure-boot-keys.md](secure-boot-keys.md). The release-signing half
(`sysupdate-signing.asc` / `import-pubring.pgp`, the committed
`files/os/sysupdate-keys/import-pubring.gpg`, and rotation):
[systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).

**Rotating any key needs a new `image-version`.** Every key ends up in the
image bits: DB signs the UKIs and systemd-boot, the module certificate is
built into the kernel, and `import-pubring.pgp` ships in `/usr`. An image
version names one immutable set of bits, and `systemd-sysupdate` only
installs a version newer than the one it runs, so rebuilding the same version
with new keys publishes different bits under a released name and never
reaches nodes already on it. Rotate keys, then `just set-version` to a
version that sorts higher before building.

## Reproducible builds

With the same checkout, keys and `image-version`, rebuilding the final
assembly gives the same bytes. BuildStream exports `SOURCE_DATE_EPOCH` into
every sandbox and the assembly steps honor it: `mkfs.erofs` and
`systemd-repart` clamp file times to it, the initrd and ESP trees are clamped
before `cpio` and `mcopy` copy them, and `systemd-sbsign` (not `sbsign`)
uses it as the signing time of systemd-boot and the UKIs. `systemd-repart
--seed` fixes partition UUIDs.

Two outputs carry a signing time of their own: `SHA256SUMS.gpg` and the
`efi-keys/*.auth` updates, which `sbvarsign` stamps with the current time
(they stay fixed as long as `bluefin-server/keys/efi-keys.bst` stays
cached). `.github/workflows/reproducibility.yml` checks the rest weekly:
it builds, deletes the final-assembly artifacts, rebuilds them without remote
caches, and compares every file except `*.gpg`.

## Dogfood: boot it in QEMU

All dogfood paths boot with Secure Boot firmware (OVMF secboot). The firmware
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
```

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
- `DOGFOOD_NODE_IGN=<file>` — serve it as `bluefin-node.ign` next to the UKI
  (picked up by HTTP-booted nodes with no Ignition credential).
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
[ci-tooling.md](ci-tooling.md) (the `boot-test` job).

## Local builds with a remote cache

If you must build locally with the cluster cache, point BuildStream at your
cache tunnel host (`<build-cache-host>`) in `~/.config/buildstream.conf`:

```yaml
projects:
  bluefin-server:
    artifacts:
      override-project-caches: false
      servers:
      - url: grpc://127.0.0.1:8980
        push: true
```

## Release automation

`.github/workflows/build.yml` runs `just validate`, exports the image set
(already carrying its signed `SHA256SUMS(.gpg)`), runs the QEMU boot test, and
on `main` publishes `dist/diskless/` as-is (see the `release` job in
[ci-tooling.md](ci-tooling.md)). One version is published
exactly once; creating an existing tag fails rather than overwriting assets
nodes may already trust.

## Common rationalizations

| Rationalization | Reality |
|---|---|
| "Skip `gen-dev-keys`, the build has defaults." | Signing needs real key material in `files/boot-keys/`; the recipe generates throwaway keys so local builds boot under Secure Boot. |
| "Test the UKI with `-kernel`/`-initrd`." | That bypasses the signed boot chain. The dogfood scripts boot the netboot ESP or installed disk through OVMF the way firmware does. |
| "Reboot loops mean the boot hung." | With Secure Boot in setup mode the first boot enrolls keys and reboots; that is expected once per fresh variable store. |
| "A failed update needs manual recovery." | Boot counting handles it: three failed boots of the new UKI and systemd-boot falls back to the previous image; `bluefin-boot-deadline` reboots a boot that comes up with a failed unit. `dogfood-install.sh <dir> <next> <broken>` proves it (`DOGFOOD_BROKEN=unit` for the failed-unit case). |
| "`chmod 4755` in install-commands makes a file setuid in the image." | No. BuildStream artifacts keep one executable bit per file, so every staged file is 0644/0755. FSDK components declare their special modes as initial scripts, and `oci/bluefin-server-usr.bst` runs them (`os-initial-scripts.bst`) while assembling /sysroot; special modes must be set in the `script` element that writes the image. |

## Red flags

- A boot cmdline with a hardcoded device path.
- An initrd change that drops `loop`, `dm-verity`, `erofs`, or `virtio_net`
  (the build fails the check in `bluefin-server-boot.bst`).
- A new release asset that is not added to `SHA256SUMS` in
  `oci/bluefin-server-image.bst`.
- Keys committed anywhere outside the gitignored `files/boot-keys/`.

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] `just dogfood-check` passes.
- [ ] `just dogfood-install NEXT=<dir>` passes when changing install or update logic.
- [ ] Exported `dist/diskless/` contains the OS DDI, both UKIs, the netboot
      ESP, the sysext assets, `efi-keys/`, `SHA256SUMS`, and `SHA256SUMS.gpg`.

## See also

- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (OS DDI, Installer, Netboot UKI, Disk UKI).
