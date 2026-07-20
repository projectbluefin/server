---
name: architecture-roadmap
description: Roadmap for future Bluefin Server architecture work. Use when planning long-lead systemd-native capabilities.
metadata:
  type: reference
  status: stable
  last_updated: "2026-07-20"
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
| 4 | Broader `systemd-creds` integration for SSH keys and network configuration | Only `root` password credential path is shipped in `os-creds-prov.bst`. |
| 5 | TPM2-bound credential delivery at first boot | Documented but not wired into the installed OS image. |
| 6 | Native reboot coordination for non-Kubernetes and single-node hosts | Kured only covers Kubernetes nodes; no FleetLock/locksmith equivalent. |
| 7 | Staged rollout behavior for larger fleets | Future after items 1-3 are implemented. |

## Status notes

- The current tree intentionally favors a single-slot update path and a single signed manifest flow.
- Any implementation work should preserve the current systemd-native model and avoid custom daemons.
- See [gap-analysis-distros.md](gap-analysis-distros.md) for the source-verified comparison that produced this list.
