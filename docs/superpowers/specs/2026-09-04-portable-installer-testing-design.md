# Portable Installer-to-Boot Test

Date: 2026-09-04
Repository: `projectbluefin/server`
Scope: A self-contained local acceptance test for the existing installer.

## Goal

Provide one clean, deterministic command that builds the Server installer,
installs it to a fresh virtual disk, boots the installed disk, and returns an
acceptance result. It must work without any lab or developer-specific
infrastructure and must not change the image being tested.

## Decisions

### Command UX

The canonical command is:

```sh
just test
```

It depends on the existing local installer export path and then performs the
installer-to-boot acceptance test. The existing lower-level
`build-installer` and `export-installer` commands remain available for
operators who need their portable artifacts directly.

Replace the opaque, interactive `show-me-the-future` command. Do not add
alternative VM-backend, pipeline, or environment-selection targets.

### Host test harness

Move the existing host-only QEMU lifecycle out of the Justfile into one
focused executable harness. It will:

1. Require QEMU/KVM, `zstd`, and UEFI firmware, with clear host-side errors.
2. Decompress the exported installer image and make a temporary writable
   target disk.
3. Boot the existing unattended installer using KVM, UEFI, and virtio disks;
   require the installer's existing clean power-off.
4. Reboot from the target disk alone, capture serial output, and accept only
   the established systemd boot milestone with no fatal/panic markers.
5. Exit nonzero on a missing prerequisite, timeout, QEMU error, installer
   failure, or failed boot assertion. Clean temporary files on success and
   retain the diagnostic directory plus serial logs on failure.

The harness is host test code, not a guest installer script. It adds no
service, shell, package, user, credential, or test signal to the DDI or UKI.

### Virtualization scope

Use the installed `qemu-system-x86_64` Linuxbrew formula with KVM and OVMF.
This is the existing compatible path and does not add a dependency on this
host.

gVisor is a container syscall-sandbox runtime, not a full-system VM.
Firecracker requires a supplied kernel and root filesystem rather than UEFI
boot media. Cloud Hypervisor can boot UEFI raw disks but is not available in
the current Linuxbrew formula set and would require separately managed
firmware. None are introduced.

## Files

Expected implementation changes:

- `Justfile`: replace `show-me-the-future` with a single `test` target that
  depends on `export-installer` and calls the host test harness.
- Add one focused host test-harness file for the QEMU process, serial capture,
  timeouts, and cleanup.
- `AGENTS.md`, `README.md`, `docs/skills/ddi-installer-build.md`, and active
  Server specifications: replace the retired command name with `just test`.

No local-lab configuration, registry, workflow, Kubernetes, KubeVirt, Dagger,
or image-build element changes are in scope.

## Validation

1. Run `just validate`.
2. Confirm `just --list` presents the single `test` acceptance command.
3. Run `just test` and require an unattended install followed by an
   installed-disk-only UEFI boot that reaches the serial systemd milestone.
4. Confirm failure preserves the named diagnostic directory and serial logs.
5. Search for stale active `show-me-the-future` references.

## Non-goals

- Changing the Server image, DDI, UKI, or installer implementation.
- Adding test-only guest behavior or SSH readiness.
- Adding VirtualBox, gVisor, Firecracker, Cloud Hypervisor, Dagger, or
  any local-lab integration.
