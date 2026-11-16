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

Toolboxes are imported and managed independently. Homebrew is not a system
container; see [homebrew-seed.md](homebrew-seed.md).

## When to Use

- Shipping a development or debugging toolbox as a `systemd-nspawn` rootfs.
- Documenting how operators import, start, enter, and reset a machine image.
- Changing `files/bin/system-container`.

## When NOT to Use

- Adding a distroless OCI runtime image — the server repo does not build those.
- Kubernetes workload or cluster questions — use `k0s-sysext.md`.

## Operator guide

User-facing setup, host/guest checks and the Ubuntu
toolbox example live in [System Containers](https://docs.projectbluefin.io/server/system-containers).
Keep operator procedures there and implementation contracts below.

## Verification

- [ ] `files/bin/system-container` exists and maps to valid `machinectl` commands.
- [ ] Image imports use `importctl` with a verified local rootfs archive.
- [ ] Host/guest boundaries and toolbox procedures stay in the linked operator guide.

## See also

- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
- `machinectl(1)`, `importctl(1)`, `systemd-nspawn(1)`, `systemd-detect-virt(1)`
