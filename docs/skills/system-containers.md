---
name: system-containers
description: Add or document system containers that should behave like first-class systemd machines rather than podman/OCI workloads. Use when managing container lifecycle with machinectl and systemd-run.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-24"
  context7-sources:
    - /systemd/systemd
---
# system containers

Use this skill when adding or documenting system containers that should behave
like first-class systemd machines rather than podman/OCI workloads.

A system container runs another Linux userspace with the host's kernel. It is
not a VM, an OCI workload, or a layer merged into the host's `/usr`.

Homebrew runs as the managed machine `bluefin-homebrew`; separate toolboxes are
imported and managed independently.

## When to Use

- Shipping a development or debugging toolbox as a `systemd-nspawn` rootfs.
- Documenting how operators import, start, enter, and reset a machine image.
- Changing `files/bin/system-container` or the bridge in `files/homebrew/`.

## When NOT to Use

- Adding a distroless OCI runtime image — the server repo does not build those.
- Kubernetes workload or cluster questions — use `k0s-sysext.md`.

## Operator guide

User-facing setup, host/guest checks, Homebrew administration and the Ubuntu
toolbox example live in [System Containers](https://docs.projectbluefin.io/server/system-containers).
Keep operator procedures there and implementation contracts below.

## Transparent Homebrew profile

The optional `homebrew` sysupdate feature downloads two signed, host-version-locked
assets, decompressing them to `/var/lib/machines/homebrew_<ver>.raw` and
`/var/lib/extensions/homebrew-integration_<ver>.raw`. The latter contains the
helper, restricted all-users sudo rule, lifecycle units, shell/SSH hooks and
Python closure. None of that bridge ships in the base OS. Ship this consumer only
with a merged producer main SHA; the producer owns its independent FSDK machine.

Apply the published, self-contained `home-server.bu` through the existing
Ignition provisioning flow. Its canonical selector runs before signed feature
fetching; a profile-only gate starts the newly merged Homebrew service before
console/SSH login. Explicit engine credentials, persisted selections and effective
sysupdate drop-ins preserve operator policy and data. Podman defaults on only in
this selected profile; Docker and the cluster stay off. Runtime activation and
private endpoints are documented in [systemd-sysext-extensions.md](systemd-sysext-extensions.md).
Provision a nonroot owner and private account/key credentials for headless use;
otherwise owner setup uses the console before getty. See
[tpm2-credential-sealing.md](tpm2-credential-sealing.md) for credential transport.

### Storage and package updates

Installed packages persist at `/var/lib/bluefin-homebrew/prefix`, bound into the
machine at `/home/linuxbrew/.linuxbrew`. The root-owned owner record prevents a
silent UID/GID change. Only the owner runs `brew`; other provisioned users execute
installed tools with a read-only prefix. User scopes keep detached tmux sessions
alive after SSH disconnects, without nesting host engine workloads in the machine.
After login readiness, `bluefin-homebrew-default-formulae.service` (in
`home-server.bu` only) runs `brew install tmux neovim` as the owner through the
same dispatch. Login never waits for it; a failed run (no network) retries next
boot. The `/var/lib/bluefin-homebrew/default-formulae` stamp keeps it from running
again, so formulae the owner removes stay removed.

Shared-cwd authorization comes from caller homes and explicit `PROJECT_ROOTS`
in root-owned `/etc/bluefin-homebrew.conf`; dispatch rejects other working
directories. Preparation rebuilds guest `/etc` at `/run/bluefin-homebrew/etc`
on host boot or an explicit preparation rerun. Restarting only the machine does
not rerun the active `RemainAfterExit` preparation service. Guest `/var` is bound
from persistent `/var/lib/bluefin-homebrew/guest-var`; other overlay writes are
discarded when the machine stops.

The guest command launcher sets `HOMEBREW_NO_AUTO_UPDATE=1` and
`HOMEBREW_NO_INSTALL_CLEANUP=1`, keeping package updates and cleanup explicit.

Dispatch preserves sudo's authenticated active primary GID, NSS supplementary
groups and inherited descriptors. Shared cwd identity is pinned and compared in
host and guest, then reopened under caller permissions before execution; `/`
deliberately maps to the guest root. Environment/package argv travel in a sealed,
caller-owned request, never sudo argv. Native allowed/denied sudo audit events
remain enabled, and user scopes have a fixed description. Foreground PTYs relay
input; background jobs retain their streams. Application output and independent
system auditing remain outside this argv privacy guarantee.

## Verification

- [ ] `files/bin/system-container` exists and maps to valid `machinectl` commands.
- [ ] Image imports use `importctl` with a verified local rootfs archive.
- [ ] Host/guest boundaries and toolbox procedures stay in the linked operator guide.

## See also

- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
- `machinectl(1)`, `importctl(1)`, `systemd-nspawn(1)`, `systemd-detect-virt(1)`
