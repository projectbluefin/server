---
name: factory-integration
version: "1.0"
last_updated: "2026-07-20"
tags: [factory, lab, k3s, fsdk-containers, workloads]
description: "Understand Bluefin Server's role as the core OS for the Project Bluefin agentic factory and how fsdk-containers workloads run on it. Use when reasoning about factory architecture, the k3s sysext, or server/lab boundaries."
metadata:
  type: reference
  context7-sources: []
---

# Factory Integration

Bluefin Server is not a generic server distribution — it is the core operating
system for the **Project Bluefin agentic OS factory**.

The factory is instantiated in [`projectbluefin/lab`](https://github.com/projectbluefin/lab):
a GitOps-driven, CNCF-native CI lab running k3s, KubeVirt, Argo Workflows, and
Argo CD on bare metal (`ghost`/`exo-1`). That lab is the first production use
of Bluefin Server and directly shapes its design.

## Factory relationship

```
┌─────────────────────────────────────────────────────────────┐
│  Project Bluefin agentic factory (projectbluefin/lab)       │
│  GitOps-driven testing and CI for image-based Linux OSes    │
│  • k3s control plane                                        │
│  • KubeVirt VM workloads                                    │
│  • Argo Workflows + Argo CD                                 │
│  • OCI/bootc image-poll lanes for bluefin, dakota, common   │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼ runs on
┌─────────────────────────────────────────────────────────────┐
│  Bluefin Server (this repo)                                 │
│  Core server OS: DDI-first, image-updated, distroless       │
│  • systemd-sysupdate for atomic A/B updates                 │
│  • systemd-sysext for optional layers (k3s, extensions)     │
│  • podman for container workloads                           │
└─────────────────────────────────────────────────────────────┘
```

## k3s is a sysext, not base image bloat

Kubernetes is **not** baked into the OS DDI. The base image stays small and
stateless; k3s is delivered as a `systemd-sysext` EROFS image that overlays
`/usr/` at runtime. This matches the factory layout:

- `elements/oci/k3s-sysext.bst` builds the sysext.
- `files/os/sysupdate.d/70-k3s.transfer` enables OTA updates of the sysext.
- `files/os/justfile` provides the `just k8s server|agent` entrypoint.

See [`k3s-sysext.md`](k3s-sysext.md) for details.

## Workloads are containers

The workloads the factory tests and ships live in other repos:

- [`projectbluefin/fsdk-containers`](https://github.com/projectbluefin/fsdk-containers) —
  distroless container images carved from FSDK components.
- `projectbluefin/bluefin`, `projectbluefin/bluefin-lts`, `projectbluefin/dakota` —
  desktop and bootc variant images.

Bluefin Server hosts those workloads via podman. The factory lab runs many of
them as Kubernetes pods inside the published OCI images. In other words:

> **Bluefin Server is the factory floor; `fsdk-containers` are the products and
> test workloads that run on that floor.**

## Why this matters for server design

The factory requirements are why Bluefin Server is built the way it is:

| Factory need | Server decision |
|---|---|
| Fully automated, GitOps-driven installs | Offline DDI installer (`systemd-sysinstall`) |
| Atomic, rollback-capable updates | Image-based A/B updates via `systemd-sysupdate` |
| Minimal attack surface / no shell in OS | Distroless DDI; optional tools as sysexts |
| Kubernetes control plane on every node | k3s delivered as `systemd-sysext` |
| Container workloads | `podman` in the base OS stack |
| Signed, verifiable release artifacts | GPG-signed `SHA256SUMS` + `import-pubring.pgp` |

## When to Use

- Explaining why a server feature exists (e.g. sysext-first design, offline
  installer, image updates).
- Deciding whether a new component belongs in the base DDI or in a standalone
  `systemd-sysext`.
- Integrating server builds with the lab/factory pipeline.
- Onboarding a new contributor who asks "what is Bluefin Server for?"

## When NOT to Use

- For desktop variant questions — see those repos.
- For container image authoring — see `fsdk-containers`.
- For lab operational troubleshooting — see `projectbluefin/common`
  `lab-testing.md` and `projectbluefin/lab`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "k3s should be in the base image." | Keep the OS DDI minimal. k3s is optional and delivered OTA as a sysext, exactly like the factory expects. |
| "We can pull the DDI at install time." | The factory runs unattended. Network failures must not break installs; the DDI is embedded in the installer media. |
| "Let's add a shell for debugging." | Shells belong in sysexts or system containers, not in the distroless DDI that runs the factory. |
| "Package updates are small patches." | Image-based updates are whole-OS replacements; rollbacks are the atomic unit, not per-package deltas. |

## Red Flags

- Adding a workload dependency to `elements/bluefin-server/os-stack.bst` that
  could ship as a `systemd-sysext` instead.
- Treating Bluefin Server as a generic Fedora/RHEL replacement rather than the
  factory core OS.
- Putting Kubernetes tooling in the base DDI and not in the k3s sysext.
- Designing install/update paths that require interactive human steps in the
  factory.

## Verification

- [ ] Any new base-DDI dependency can be justified by the factory core-OS role.
- [ ] Optional capabilities are modeled as sysexts or system containers.
- [ ] The k3s sysext still builds and updates independently of the DDI.
- [ ] `systemd-sysupdate` transfer files are present for every OTA-delivered
      artifact (DDI, UKI, k3s sysext).
