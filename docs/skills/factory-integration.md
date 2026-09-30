---
name: factory-integration
description: Understand Bluefin Server's role as the core OS for an image-based CI/OS factory and how optional workloads run on it.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-28"
---
# Factory Integration

Bluefin Server is not a generic server distribution; it is the core operating system for an image-based CI/OS factory.

The factory pattern is broader than a single host: a downstream CI lab or OS factory uses Bluefin Server as the base OS for automated provisioning, image-based updates, and optional runtime workloads. That environment shapes the design of this repository.

## Factory relationship

```
┌─────────────────────────────────────────────────────────────┐
│ Downstream CI lab / OS factory                              │
│ GitOps-style testing and automation for image-based OSes    │
│ • k0s control plane / workload orchestration                │
│ • VM or container workloads                                 │
│ • OCI/bootc image pipelines / release automation            │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ runs on
┌─────────────────────────────────────────────────────────────┐
│ Bluefin Server (this repo)                                  │
│ Core server OS: DDI-first, image-updated                    │
│ • systemd-sysupdate for atomic A/B updates                  │
│ • systemd-sysext for optional layers (k0s, extensions)      │
└─────────────────────────────────────────────────────────────┘
```

## k0s is a sysext, not base image bloat

Kubernetes is not baked into the base /usr image. The base image stays small and stateless; k0s is delivered as a `systemd-sysext` EROFS image that overlays `/usr/` at runtime.

- `elements/oci/k0s-sysext.bst` builds the sysext.
- `files/os/sysupdate.k0s.d/70-k0s.transfer` enables component-scoped OTA
  updates of the sysext.
- `files/os/justfile` provides the `just k8s` entrypoint.

See [k0s-sysext.md](k0s-sysext.md) for details.

## Workloads are containers

The workloads the factory tests and ships live in other repositories or image
pipelines. No container runtime ships in the base /usr image (hard rule 4);
the only runtime we ship is containerd, inside the opt-in kubeadm sysext (see
[kubeadm-sysext.md](kubeadm-sysext.md)). Everything else runs in system
containers or in the workload images themselves.

> Bluefin Server is the factory floor; optional workloads and variant images run on that floor.

## Why this matters for server design

| Factory need | Server decision |
|---|---|
| Fully automated, unattended installs and rebuilds | Diskless network boot; a booted node installs itself with `systemd-sysinstall` |
| Atomic, rollback-capable updates | Image-based A/B updates via `systemd-sysupdate`; diskless nodes update by rebooting |
| Minimal attack surface / lean base OS | Verity-sealed read-only /usr with bash; optional tools as sysexts |
| Kubernetes control plane on every node | k0s delivered as `systemd-sysext` |
| Container workloads | containerd via the opt-in kubeadm sysext; anything else runs in system containers |
| Signed, verifiable release artifacts | Signed UKIs + `SHA256SUMS` signed in-element, verified against `/etc/systemd/import-pubring.pgp` |

## SSH and Remote Diagnostics

> `sshd` is present in the OS image for on-demand diagnostics and bring-up troubleshooting, but is disabled by default via `disable sshd.service` in systemd presets. Operators can start it on-demand with `systemctl start sshd` or enable it when remote access is required. Login is key-only (`PermitRootLogin prohibit-password`, `PasswordAuthentication no`), and root ships locked; provision keys per node as described under "Node access" in [tpm2-credential-sealing.md](tpm2-credential-sealing.md).

## When to Use

- Explaining why a server feature exists (diskless-first boot, sysext-first design, image updates).
- Deciding whether a new component belongs in the base /usr image or in a standalone `systemd-sysext`.
- Integrating server builds with the factory CI repository or image-factory pipeline.
- Onboarding a contributor who asks “what is Bluefin Server for?”

## When NOT to Use

- For desktop variant questions — see those repos or image pipelines.
- For container image authoring — see the relevant packaging or build docs.
- For lab operational troubleshooting — see the factory CI repository maintainer documentation.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| “k0s should be in the base image.” | Keep the base /usr minimal. k0s is optional and delivered OTA as a sysext. |
| “The USB installer needs its own installer logic.” | It is the same image booted from a stick into stock `systemd-sysinstall.service`; the install path and the installed disk are identical to a diskless install. |
| “Let’s add heavy debug tools.” | Base OS includes bash for login; heavy developer/debug tools belong in sysexts or system containers. |
| “Package updates are small patches.” | Image-based updates are whole-OS replacements; the rollback unit is the OS image, not a package delta. |

## Red Flags

- Adding a workload dependency to `elements/bluefin-server/os-stack.bst` that could ship as a `systemd-sysext`.
- Treating Bluefin Server as a generic Fedora/RHEL replacement rather than the factory core OS.
- Putting Kubernetes tooling in the base /usr image instead of the k0s sysext.
- Designing install/update paths that require interactive human steps in the factory.

## Verification

- [ ] Any new base-image dependency can be justified by the factory core-OS role.
- [ ] Optional capabilities are modeled as sysexts or system containers.
- [ ] The k0s sysext still builds and updates independently of the base image.
- [ ] `systemd-sysupdate` transfer files are present for every OTA-delivered artifact (usr, usr-verity, UKI, k0s sysext).

## See also

- [k0s-sysext.md](k0s-sysext.md) — building and delivering the k0s sysext.
- [ddi-installer.md](ddi-installer.md) — boot, install, and update architecture.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
