---
name: architecture-roadmap
description: Roadmap for future Bluefin Server architecture work. Use when planning long-lead systemd-native capabilities.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-07"
  context7-sources:
    - /systemd/systemd
---

# Architecture Roadmap

Status: current roadmap.

This file captures planned architecture work and the rationale behind it. Verified implementation rules now live in [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md), [tpm2-credential-sealing.md](tpm2-credential-sealing.md), and [systemd-sysext-extensions.md](systemd-sysext-extensions.md).
The source-verified gap analysis lives in [gap-analysis-distros.md](gap-analysis-distros.md).

## Planned work

Priorities are derived from [gap-analysis-distros.md](gap-analysis-distros.md).

| # | Item | Rationale / source gap |
|---|------|------------------------|
| 1 | A/B dual-slot root partitions with matching ESP/UKI slots | Root fs only has slot A today; sysupdate already names slots A+B. |
| 2 | Mount `/usr` read-only and enforce the state model | DDI is currently booted `rw`; sysext-first design assumes immutable `/usr`. |
| 3 | Boot-time selection / automatic rollback of a failed update | No previous OS version is kept once a root update overwrites the slot. |
| 4 | Credential provisioning smoke tests on real hardware | SSH keys, static network, and firstboot settings are wired through systemd credentials; TPM2-sealed credential decryption still needs hardware proof. |
| 5 | Distributed reboot lock coordination for multi-node non-Kubernetes clusters | Single-node / maintenance window / lock-file reboot coordination is present via `systemd-sysupdate-reboot`; cluster-wide FleetLock/locksmith HTTP protocol is not implemented. |
| 6 | Staged rollout behavior for larger fleets | Future after items 1-3 are implemented. |

## Status notes

- The current tree intentionally favors a single-slot update path and a single signed manifest flow.
- Any implementation work should preserve the current systemd-native model and avoid custom daemons.
- See [gap-analysis-distros.md](gap-analysis-distros.md) for the source-verified comparison that produced this list.

## See also

- [gap-analysis-distros.md](gap-analysis-distros.md) — source-verified distro comparison.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
