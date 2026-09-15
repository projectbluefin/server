# ADR: Scope FSDK composition to the installer

**Status:** Accepted

## Context

Bluefin Server currently builds the installer and installed OS payload in one
FSDK-oriented composition model. The installed OS already imports Flatcar's
kernel and ZFS system extension as pinned binary artifacts, and the Flatcar
base migration extends that model to the OS payload's userspace and runtime
system extensions.

The installer still needs FSDK because it relies on `systemd-sysinstall`, which
Flatcar does not ship. The installed OS payload does not need that tool after
the DDI is built; the installer writes the DDI by `CopyBlocks=`, a byte-level
contract that does not inspect the payload's userspace.

## Decision

Hard rule 1 is scoped to the installer image: installer elements continue to
compose from FSDK 26.08 `components/*` and must not use `platform.bst`.

The installed OS payload may import Flatcar OS and system-extension binaries
when the imported artifact is pinned by digest in BuildStream. This matches the
existing `flatcar/flatcar-kernel.bst` and `flatcar/flatcar-zfs.bst` model and
keeps the OS payload on a single upstream ABI domain as the Flatcar migration
lands.

Hard rules 2-6 remain active. The CPU baseline remains broad, the installer
stays `systemd-sysinstall`-native and `systemd-repart`-based, boot entries keep
using GPT `PARTUUID`, and duplicated sources of truth remain prohibited.

Regarding Hard Rule 4 ("Deliver k0s as an optional `systemd-sysext`; never bundle
Kubernetes or container runtimes into the base OS DDI"): container runtimes
(podman, containerd, docker) and Kubernetes distributions must remain delivered
via standalone system extension images (`systemd-sysext` `.raw` files under
`/usr/lib/sysexts`), rather than being baked directly into the base OS `/usr`
payload filesystem. Staging `.raw` sysext files under `/usr/lib/sysexts` for
runtime attachment satisfies this boundary.

## Rejected alternatives

### Rebuild Flatcar from source in BuildStream

Rejected. Flatcar is a Gentoo/portage-based cross-build. Reproducing that build
inside this repository's BuildStream project would create a second upstream
build system with large maintenance cost and no additional local contract over
a digest-pinned upstream artifact.

### Keep the status quo hybrid

Rejected. Keeping FSDK userspace in the OS payload while importing Flatcar
kernel and ZFS artifacts preserves the ABI split that the migration is meant to
remove. It also keeps `ID=flatcar` as a compatibility fiction rather than the
installed OS payload's real identity.
