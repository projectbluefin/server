---
name: skills-index
version: "2.0"
last_updated: "2026-07-19"
tags: [skills, routing, index]
description: |
  Lazy-load manifest for Bluefin Server agent skills. Start here after AGENTS.md.
metadata:
  type: index
skills:
  - id: avoid-over-engineering
    file: avoid-over-engineering.md
    trigger: "over-engineering, bloat, cut scope, yagni"
    description: Rules and red flags for keeping solutions small.
  - id: bump-fsdk-version
    file: bump-fsdk-version.md
    trigger: "fsdk, version, retag, junction"
    description: Update the pinned FSDK release and derived tags.
  - id: ci-tooling
    file: ci-tooling.md
    trigger: "ci, github actions, sha pin, workflow"
    description: CI conventions and GitHub Actions security rules.
  - id: ddi-installer
    file: ddi-installer.md
    trigger: "installer, ddi, systemd-sysinstall, systemd-repart"
    description: Build and debug the live installer media.
  - id: factory-integration
    file: factory-integration.md
    trigger: "factory, downstream, lab, k3s sysext"
    description: Server OS role inside the larger CI/OS factory.
  - id: gap-analysis-architecture
    file: gap-analysis-architecture.md
    trigger: "gap analysis, roadmap, architecture"
    description: Design rules and future architecture notes.
  - id: k3s-sysext
    file: k3s-sysext.md
    trigger: "k3s, sysext, kubernetes"
    description: Build, ship, and enable the k3s systemd-sysext.
  - id: skill-improvement
    file: skill-improvement.md
    trigger: "skill, documentation, improvement, handoff"
    description: Maintain the skill library and the work+learning loop.
  - id: system-containers
    file: system-containers.md
    trigger: "system container, machinectl, nspawn"
    description: Manage system containers on the host.
  - id: systemd-sysext-extensions
    file: systemd-sysext-extensions.md
    trigger: "sysext, confext, extension, overlay"
    description: Work with systemd-sysext and systemd-confext overlays.
  - id: systemd-sysupdate-verification
    file: systemd-sysupdate-verification.md
    trigger: "sysupdate, signing, sha256sums, gpg, release"
    description: Release signing and OTA update trust model.
  - id: tpm2-credential-sealing
    file: tpm2-credential-sealing.md
    trigger: "tpm2, credential, sealing, tpm"
    description: Secure provisioning credentials with TPM2 sealing.
---

# docs/skills — Index

Start at [AGENTS.md](../../AGENTS.md), then load the skill that matches your
task. The YAML front matter above is the machine-readable manifest.

## Routing table

| ID | File | Use when... |
|----|------|-------------|
| avoid-over-engineering | [avoid-over-engineering.md](avoid-over-engineering.md) | cutting bloat / resisting over-engineering |
| bump-fsdk-version | [bump-fsdk-version.md](bump-fsdk-version.md) | updating the FSDK pin |
| ci-tooling | [ci-tooling.md](ci-tooling.md) | writing or debugging CI workflows |
| ddi-installer | [ddi-installer.md](ddi-installer.md) | building or debugging the installer |
| factory-integration | [factory-integration.md](factory-integration.md) | factory role or downstream composition |
| gap-analysis-architecture | [gap-analysis-architecture.md](gap-analysis-architecture.md) | architecture roadmap / gaps |
| k3s-sysext | [k3s-sysext.md](k3s-sysext.md) | building or shipping the k3s sysext |
| skill-improvement | [skill-improvement.md](skill-improvement.md) | adding or refactoring skills |
| system-containers | [system-containers.md](system-containers.md) | system containers with machinectl |
| systemd-sysext-extensions | [systemd-sysext-extensions.md](systemd-sysext-extensions.md) | sysext / confext overlays |
| systemd-sysupdate-verification | [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) | release signing / sysupdate trust |
| tpm2-credential-sealing | [tpm2-credential-sealing.md](tpm2-credential-sealing.md) | TPM2 credential sealing |

## Standing facts

- BuildStream runs in the FSDK `bst2` container via `just bst`. Local requirements:
  `podman` + `just`.
- Compose from FSDK `components/*`, never `platform.bst`.
- The interactive installer is `systemd-sysinstall` (systemd 261+).
- The installer is offline: the DDI is embedded as a data partition.
- `just validate` is the merge contract for element graph changes.
