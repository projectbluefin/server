---
name: ddi-installer-build
description: Build, export, and dogfood the Bluefin Server image set (OS DDI, signed UKIs, netboot ESP) and the opt-in sysexts.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-17"
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
    - /websites/man7_linux_man-pages
    - /nixos/patchelf
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
just gen-dev-keys      # throwaway Secure Boot keys + the public dev module key in files/boot-keys/
just set-version V     # set image-version in include/image.yml (<=17 chars,
                       # increasing under strverscmp)
just build-image       # build oci/bluefin-server-image.bst
just export-image      # export the release set to dist/diskless/
just build-sysext      # build oci/k0s-sysext.bst
just export-sysext     # export k0s sysext + SHA256SUMS to dist/sysext/
just build-zfs-sysext  # build oci/zfs-sysext.bst
just export-zfs-sysext # export OpenZFS sysext + SHA256SUMS to dist/sysext/
just build-nvidia-sysext  # build oci/<flavour>-sysext.bst (nvidia-open-595)
just export-nvidia-sysext # export NVIDIA sysext + SHA256SUMS to dist/sysext/
just dogfood-nvidia       # QEMU disk install + merge/probe dist/diskless/'s NVIDIA sysext
just version / just tags  # FSDK-derived point release and tag set
just check-image [DIR] [BASELINE]  # broken-reference check of an exported set
```

`just export-image` writes one directory per image version containing the OS
DDI, the sysupdate usr/usr-verity sources, both UKIs, the netboot ESP image,
the k0s/KubeStellar/OpenZFS sysext assets, the `efi-keys/` enrollment
payloads, and a `SHA256SUMS` over all of it with its detached signature
`SHA256SUMS.gpg` (signed in-element by `oci/bluefin-server-image.bst`). See
[ddi-installer.md](ddi-installer.md) for what each artifact is.

Home Server builds `homebrew/image.bst` through `fsdk-containers.bst`; the
producer exports its independently pinned Brew machine, not host binaries.
Keep the host and producer FSDK junctions explicitly duplicated in `project.conf`:
their filesystems are packaged separately. Share the identical community-plugin
junction through the consumer override; recheck its pins before changing that
mapping. Text-only manual elements use `strip-binaries: ""`, matching
`os-creds-prov.bst`, rather than adding a binary-stripping toolchain.
The separate `oci/homebrew-integration-sysext.bst` supplies the optional host
bridge and Python closure, not base `/usr`. Its version-locked asset and the
machine asset are signed together; the `homebrew` feature stages both.
Use a merged `fsdk-containers` main SHA before shipping this consumer.


To publish the set as an OCI artifact (one layer per file, tags `<version>`
and `latest`, artifact type
`application/vnd.projectbluefin.server.release.v1`):

```bash
just publish-oci ghcr.io/<owner>/bluefin-server                 # podman login first
just publish-oci <registry-host>:30500/bluefin-server dist/diskless 1  # plain HTTP
```

## bluefin-host

The base OS's non-interactive runtime helpers (update status, reboot
interlocks and FleetLock client, boot deadline, diskless update check, sysext
fetch, first-boot naming and credentials, the module-sysext loader, the
`/etc` mode repair) are one static Go binary,
`files/homelab/cluster/cmd/bluefin-host` with its packages in
`internal/host/` (standard library only, in the vendored bluefin-cluster
module). `bluefin-server/os-host.bst` builds it into `/usr/bin/bluefin-host`
and links each `/usr/libexec/bluefin-<name>` to it; the binary runs the helper
its name (or its first argument) names. Unit drop-ins call
`bluefin-host kube-interlock`, `kured-flag`, `mask-uki-transfer` and
`boot-is-good` directly. Installer helpers, the justfile and the initrd's
copy of `bluefin-boot-origin` stay shell.

```bash
cd files/homelab/cluster
gofmt -l cmd internal && go vet ./... && go test -race ./...  # as CI's go job
just bst build bluefin-server/os-host.bst                    # vet + test in-element
python3 -m pytest tests/unit -q                              # builds and runs it
```

The pytest suites build the binary once per session (`host_bin` in
`tests/unit/conftest.py`, needs `go`) and run it under the helpers' old
names against stub systemd tools on `PATH`, with the same `BLUEFIN_*`
overrides the shell helpers read.

## Keys

Every image build signs: the UKIs and systemd-boot with DB, kernel modules
with the module signing certificate, and the release `SHA256SUMS` with the
image signing key. What each key is, where it lives, what `just gen-dev-keys`
generates (throwaway keys in the gitignored `files/boot-keys/`, kept unless
`--force`, a partial set is an error, the module pair is the public
INSECURE dev pair so the kernel comes from the cache), and how CI supplies
the real keys:
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
caches, and compares every file except `*.gpg`. The final assembly
(`FINAL_ASSEMBLY`) is everything `oci/bluefin-server-image.bst` stages into
the release set plus every `oci/*` target `just validate` resolves;
`tests/unit/test_reproducibility_workflow.py` fails when a shipped element is missing.

## Dogfood: boot it in QEMU

Boot-testing the exported set — `just dogfood*`, `scripts/dogfood-*.sh`, the
`DOGFOOD_*` variables — lives in
[ddi-installer-dogfood.md](ddi-installer-dogfood.md).

## Pruning and the image check

`/usr` and the initrd are composed from whole FSDK components, so they carry
files nothing on a server node uses. Two mechanisms remove them:

- `bluefin-server/os-filesystem.bst` excludes the `locale` split domain
  (message catalogs and locale sources). Only `C.UTF-8` and `en_US.UTF-8` are
  compiled into `/usr/lib/locale`, so other catalogs could never load.
- `files/prune/` holds reviewed glob lists, applied by `files/prune/prune.sh`:
  `common.list` to both trees, then `usr.list` in `oci/bluefin-server-usr.bst`
  or `initrd.list` in `oci/bluefin-server-boot.bst`. Each entry states why
  nothing uses it. A pattern that matches nothing fails the build, so the
  lists cannot go stale after an FSDK bump. The initrd also keeps only the
  terminfo entries named in `initrd-terminfo` in `bluefin-server-boot.bst`.

`just check-image [DIR] [BASELINE]` (`.github/scripts/check-image.py`)
extracts the `/usr` image, the disk UKI's initrd, and every sysext, and fails
when any ELF `DT_NEEDED` library, any `required` `.note.dlopen` library, or
any program named by a unit `Exec*=` line or a udev
`RUN`/`PROGRAM`/`IMPORT{program}` is missing. Sysexts resolve over `/usr`.
`-`-prefixed commands and programs guarded by a `ConditionPathExists=` are
skipped. With `BASELINE` (an older `*.usr.raw`) it also lists the `/usr`
paths added and removed. Pre-existing FSDK gaps are waived in `KNOWN_BROKEN`
in the script; that set is shrink-only (an entry that no longer matches fails
the check). CI runs it as the `image-check` job against the latest release.

Only prune what the check can prove unused, or what nothing outside an
interactive shell runs. Kernel modules, hwdb, keymaps and tools users run
directly are product decisions, not prune-list entries. Decided so far: the
drivers whose hardware needs firmware the image never ships (Wi-Fi,
Bluetooth, AMD/Radeon/Nouveau/Xe GPUs) are off in the kernel config
(`patches/freedesktop-sdk/0009`); i915, simpledrm and the virtual GPUs stay;
sound, media and IIO are untouched pending a product call. The check cannot see
programs a binary execs itself: `systemd-pull` (behind `systemd-sysupdate`)
runs `gpg`, which starts `gpg-agent` and `keyboxd`, so those stay with `gpgv`.

Disabling systemd features (homed, userdb, portabled, oomd, localed,
timedated, backlight, rfkill, hibernate, xdg-autostart) would need a patch on
FSDK's systemd element, which moves systemd and every dependent off FSDK's
artifact cache for every build; not done until measured to be worth it.

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
| "Rootless engines need setuid added to `newuidmap`/`newgidmap`." | Keep FSDK's native 0755 + `cap_setuid=ep`/`cap_setgid=ep` from its initial scripts. Adding setuid changes the effective UID while file capabilities still limit privileges; the helper then cannot open the caller's `/proc/<pid>/{uid,gid}_map`. The real rootless workload tests, not a setuid-bit assertion, are the contract. |
| "Private crun inherits the wrapper's loader environment." | Conmon sanitizes it. Set crun's RUNPATH to `$ORIGIN/../lib` and each private `libcrun.so*` to `$ORIGIN` in `runtimes/podman-runtime.bst`; retain the same pinned FSDK libraries privately. Verify `env -i /usr/lib/bluefin/podman/bin/crun --version` and a real rootless workload. |
| "The seeded prefix can become owner-writable while root walks it." | Keep the copy behind a root-owned 0700 staging envelope until all privileged traversal finishes, then publish atomically. The real unprivileged-process regression must not transfer ownership of a host directory selected by a racing symlink. |
| "A passing probe means the VM can be power-cut." | Sync after appended Home workloads, before the completion marker, then request native ACPI shutdown and await exit. Otherwise newly pulled OCI layer files can persist as empty files on the next boot. |
| "Stop nspawn with the guest init signal." | The service's main process is the supervisor, not guest PID 1. Keep default SIGTERM with `KillMode=mixed`; nspawn sends the guest's orderly signal and cleans its exports. Sending SIGRTMIN+3 to the supervisor leaves mounts that block restart. |

## Red flags

- A boot cmdline with a hardcoded device path.
- An initrd change that drops `loop`, `dm-verity`, `erofs`, or `virtio_net`
  (the build fails the check in `bluefin-server-boot.bst`).
- A new release asset that is not added to `SHA256SUMS` in
  `oci/bluefin-server-image.bst`.
- Keys committed anywhere outside the gitignored `files/boot-keys/`, other
  than the public INSECURE dev module pair in `files/dev-keys/`.
- A new `KNOWN_BROKEN` waiver in `check-image.py` to get a prune past CI.

## Verification

- [ ] `just validate` resolves the BuildStream graph without errors.
- [ ] `just dogfood-check` passes.
- [ ] `just dogfood-install NEXT=<dir>` passes when changing install or update logic.
- [ ] `just check-image` passes after changing `files/prune/` or a composed stack.
- [ ] Exported `dist/diskless/` contains the OS DDI, both UKIs, the netboot
      ESP, the sysext assets, `efi-keys/`, `SHA256SUMS`, and `SHA256SUMS.gpg`.

## See also

- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (OS DDI, Installer, Netboot UKI, Disk UKI).
