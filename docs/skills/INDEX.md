---
name: skills-index
version: "1.0"
last_updated: "2026-07-20"
tags: ['skills', 'routing', 'index']
description: "Routing table for bluefin-server skills. Load when onboarding to this repo or deciding which skill applies to your task."
metadata:
  type: index
---

# docs/skills — Index

`projectbluefin/server` is Bluefin Server — an FSDK-based, image-based Linux
server OS. Start at [AGENTS.md](../../AGENTS.md) for the project model and hard
rules, then load the focused skill for your task.

## Fast paths

| If your task is... | Load |
| ------------------ | ---- |
| Understand Bluefin Server's factory role | [factory-integration.md](factory-integration.md) |
| Build or debug the DDI live installer | [ddi-installer.md](ddi-installer.md) |
| SSH into the live installer | [ddi-installer.md](ddi-installer.md) |
| Work with systemd-sysext or confext overlays | [systemd-sysext-extensions.md](systemd-sysext-extensions.md) |
| Build, ship, or enable the k3s systemd-sysext | [k3s-sysext.md](k3s-sysext.md) |
| Add or document system containers (`machinectl`) | [system-containers.md](system-containers.md) |
| Configure `systemd-sysupdate` GPG verification | [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) |
| Review gap analysis or architectural roadmap | [gap-analysis-architecture.md](gap-analysis-architecture.md) |
| Move to a new FSDK release / retag | [bump-fsdk-version.md](bump-fsdk-version.md) |
| Write or debug a CI workflow | [ci-tooling.md](ci-tooling.md) |
| Avoid over-engineering / audit for cuts | [avoid-over-engineering.md](avoid-over-engineering.md) |
| Securing provisioning credentials (TPM2 sealing) | [tpm2-credential-sealing.md](tpm2-credential-sealing.md) |
| Finishing a task (always) | [skill-improvement.md](skill-improvement.md) |

## What belongs here

Workflow knowledge, architectural context, and operational runbooks any agent
needs to work in this repo.

## What does NOT belong here

Agent-specific instruction files (`AGENTS.md`, `.cursorrules`,
`.github/copilot-instructions.md`, etc.) are loaded separately by their
respective tools and must not be listed here.

## Standing facts

- BuildStream runs in the FSDK `bst2` container via `just bst`. Nothing to install
  but `podman` + `just`.
- Compose from FSDK `components/*`, never `platform.bst`.
- The interactive installer is **systemd-sysinstall** (added in systemd 261).
- The installer is **offline** — the DDI is embedded as a data partition. No
  network pull is required at install time.
- The live installer has no SSH server and no baked-in root credentials; all
  interaction happens on `/dev/console`.
- `just validate` is the merge contract for element graph changes.
