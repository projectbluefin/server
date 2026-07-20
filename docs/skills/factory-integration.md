---
name: factory-integration
description: Understand Bluefin Server's role as the core OS for an image-based CI/OS factory and how optional workloads run on it.
metadata:
  type: reference
  status: stable
  last_updated: 2026-07-20
---
# Factory Integration

Bluefin Server is not a generic server distribution; it is the core operating system for an image-based CI/OS factory.

The factory pattern is broader than a single host: a downstream CI lab or OS factory uses Bluefin Server as the base OS for automated provisioning, image-based updates, and optional runtime workloads. That environment shapes the design of this repository.

## Factory relationship

```
┌─────────────────────────────────────────────────────────────┐
│ Downstream CI lab / OS factory                              │
│ GitOps-style testing and automation for image-based OSes    │
│ • k3s control plane / workload orchestration                │
│ • VM or container workloads                                 │
│ • OCI/bootc image pipelines / release automation            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ runs on
┌─────────────────────────────────────────────────────────────┐
│ Bluefin Server (this repo)                                  │
│ Core server OS: DDI-first, image-updated, distroless        │
│ • systemd-sysupdate for atomic A/B updates                  │
│ • systemd-sysext for optional layers (k3s, extensions)      │
│ • podman for container workloads                            │
└─────────────────────────────────────────────────────────────┘
```

## k3s is a sysext, not base image bloat

Kubernetes is not baked into the OS DDI. The base image stays small and stateless; k3s is delivered as a `systemd-sysext` EROFS image that overlays `/usr/` at runtime.

- `elements/oci/k3s-sysext.bst` builds the sysext.
- `files/os/sysupdate.d/70-k3s.transfer` enables OTA updates of the sysext.
- `files/os/justfile` provides the `just k8s server|agent` entrypoint.

See [k3s-sysext.md](k3s-sysext.md) for details.

## Workloads are containers

The workloads the factory tests and ships live in other repositories or image pipelines. Bluefin Server hosts them via `podman`.

> Bluefin Server is the factory floor; optional workloads and variant images run on that floor.

## Why this matters for server design

| Factory need | Server decision |
|---|---|
| Fully automated, unattended installs | Offline DDI installer (`systemd-sysinstall`) |
| Atomic, rollback-capable updates | Image-based A/B updates via `systemd-sysupdate` |
| Minimal attack surface / no shell in OS | Distroless DDI; optional tools as sysexts |
| Kubernetes control plane on every node | k3s delivered as `systemd-sysext` |
| Container workloads | `podman` in the base OS stack |
| Signed, verifiable release artifacts | GPG-signed `SHA256SUMS` + `import-pubring.pgp` |

## Temporary SSH exception

> `sshd` is enabled for bring-up and cluster boot tests, and root login is permitted with password and pubkey. The lab runs the `bluefin-server-boot-test` Argo workflow (in `projectbluefin/lab`) to verify installer → first-boot success. SSH will be removed once diagnostics can be driven entirely by serial logs or a guest agent.

## When to Use

- Explaining why a server feature exists (offline installer, sysext-first design, image updates).
- Deciding whether a new component belongs in the base DDI or in a standalone `systemd-sysext`.
- Integrating server builds with the downstream CI or image-factory pipeline.
- Onboarding a contributor who asks “what is Bluefin Server for?”

## When NOT to Use

- For desktop variant questions — see those repos or image pipelines.
- For container image authoring — see the relevant packaging or build docs.
- For lab operational troubleshooting — see the downstream CI maintainer documentation.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| “k3s should be in the base image.” | Keep the OS DDI minimal. k3s is optional and delivered OTA as a sysext. |
| “We can pull the DDI at install time.” | Unattended installs must survive network loss; the DDI is embedded in the installer media. |
| “Let’s add a shell for debugging.” | Shells belong in sysexts or system containers, not in the distroless DDI. (Temporary exception: SSH during bring-up; see above.) |
| “Package updates are small patches.” | Image-based updates are whole-OS replacements; the rollback unit is the OS image, not a package delta. |

## Red Flags

- Adding a workload dependency to `elements/bluefin-server/os-stack.bst` that could ship as a `systemd-sysext`.
- Treating Bluefin Server as a generic Fedora/RHEL replacement rather than the factory core OS.
- Putting Kubernetes tooling in the base DDI instead of the k3s sysext.
- Designing install/update paths that require interactive human steps in the factory.

## Verification

- [ ] Any new base-DDI dependency can be justified by the factory core-OS role.
- [ ] Optional capabilities are modeled as sysexts or system containers.
- [ ] The k3s sysext still builds and updates independently of the DDI.
- [ ] `systemd-sysupdate` transfer files are present for every OTA-delivered artifact (DDI, UKI, k3s sysext).
