---
name: index
description: Lazy-load manifest for Bluefin Server skills. Load this file after AGENTS.md, then read only the skill that matches your current task.
metadata:
  type: index
  status: stable
  last_updated: 2026-07-20
---
# docs/skills — Index

This is the lazy-load routing table for agent skills. Keep this file in memory while you work; load only the skill file named in each row.

## Loading contract

1. Read `AGENTS.md` first.
2. Read this file.
3. Read **one** skill file from the table below that matches the current task.
4. Do not load unrelated skills. If a skill references another file, follow the link only when the referenced topic is part of the current task.

## Routing table

| Skill file | When to load | One-line scope |
|---|---|---|
| [`avoid-over-engineering.md`](avoid-over-engineering.md) | Cutting scope, deleting code, resisting bloat | Rules and red flags for keeping solutions small. |
| [`architecture-roadmap.md`](architecture-roadmap.md) | Future architecture direction, long-lead design | Roadmap for systemd-native architecture work. |
| [`bump-fsdk-version.md`](bump-fsdk-version.md) | Pinning or retagging the FSDK junction | Update the pinned FSDK release and derived tags. |
| [`ci-tooling.md`](ci-tooling.md) | GitHub Actions, workflow SHA pinning, CI conventions | CI conventions and release pipeline rules. |
| [`ddi-installer-build.md`](ddi-installer-build.md) | Building the installer or DDI on the cluster | Cluster build pipeline and local installer/DDI build. |
| [`ddi-installer.md`](ddi-installer.md) | Installer boot flow, `systemd-sysinstall`, `systemd-repart` | High-level DDI install architecture and local smoke test. |
| [`factory-integration.md`](factory-integration.md) | Lab integration, boot-test workflow, factory role | How Bluefin Server is consumed by the CI lab. |
| [`gap-analysis-distros.md`](gap-analysis-distros.md) | Comparing Bluefin Server to other server OSes | Source-verified comparison to Ubuntu, Talos, Flatcar, FCOS. |
| [`k3s-sysext-ops.md`](k3s-sysext-ops.md) | Building the k3s sysext | BuildStream element and publish steps for the k3s sysext. |
| [`k3s-sysext.md`](k3s-sysext.md) | Operating k3s on Bluefin Server | Runtime operation and reboot coordination for k3s. |
| [`skill-improvement.md`](skill-improvement.md) | Adding, splitting, or refactoring skills | Meta-skill that owns the documentation loop. |
| [`system-containers.md`](system-containers.md) | Running `systemd-nspawn` toolboxes | System container operation with `machinectl`. |
| [`systemd-sysext-extensions.md`](systemd-sysext-extensions.md) | Optional layers via `systemd-sysext` / `systemd-confext` | Extension identity, loading, and Flatcar compatibility. |
| [`systemd-sysupdate-verification.md`](systemd-sysupdate-verification.md) | Image-based A/B updates and signed manifests | Release signing, `systemd-sysupdate`, and trust model. |
| [`tpm2-credential-sealing.md`](tpm2-credential-sealing.md) | TPM2-bound first-boot credentials | Credential sealing with `systemd-creds` and TPM2. |

## Standing facts

- **Publish registry:** factory OCI registry (set by your operator).
- **Cluster build workflow:** `bluefin-server-build-pipeline` in the downstream factory CI repository.
- **Cluster boot-test workflow:** `bluefin-server-boot-test` in the downstream factory CI repository.
- **Version scheme:** FSDK-derived only; no separate application version axis.
