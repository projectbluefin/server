---
name: skills-readme
description: Routing table for bluefin-server skills. Load when onboarding to this repo or deciding which skill applies to your task.
metadata:
  type: index
---

# docs/skills — Routing

`projectbluefin/server` is Bluefin Server — an FSDK-based, image-based Linux
server OS. Start at [AGENTS.md](../../AGENTS.md) for the project model and hard
rules, then load the focused skill for your task.

## Fast paths

| If your task is... | Load |
| ------------------ | ---- |
| Build or debug the DDI live installer | [ddi-installer.md](ddi-installer.md) |
| SSH into the live installer | [ddi-installer.md](ddi-installer.md) |
| Review gap analysis or architectural roadmap | [gap-analysis-architecture.md](gap-analysis-architecture.md) |
| Add a non-distroless nspawn machine image (dev env, tarball) | [nspawn-machine-image.md](nspawn-machine-image.md) |
| Make an image smaller / apply the SLIM recipe | [slim-an-image.md](slim-an-image.md) |
| Move to a new FSDK release / retag | [bump-fsdk-version.md](bump-fsdk-version.md) |
| Prove an image is still distroless | [verify-distroless.md](verify-distroless.md) |
| Supply chain security (signing and SBOM) | [signing-and-sbom.md](signing-and-sbom.md) |
| Write or debug a CI workflow | [ci-tooling.md](ci-tooling.md) |
| Automate ArtifactHub submissions | [artifacthub-automation.md](artifacthub-automation.md) |
| Finishing a task (always) | [skill-improvement.md](skill-improvement.md) |
| Securing Provisioning Credentials (TPM2 Sealing) | [tpm2-credential-sealing.md](tpm2-credential-sealing.md) |
| Extensibility via systemd-sysext and Bakery | [systemd-sysext-extensions.md](systemd-sysext-extensions.md) |
| Avoiding over-engineering / auditing for cuts | [avoid-over-engineering.md](avoid-over-engineering.md) |

## What belongs here

Workflow knowledge and operational runbooks any agent needs to work in this repo.
**Not here:** agent-instruction files (`AGENTS.md`) — loaded separately by tools.

## Standing facts

- BuildStream runs in the FSDK `bst2` container via `just bst`. Nothing to install
  but `podman` + `just`.
- Compose from FSDK `components/*`, never `platform.bst`.
- The interactive installer is **systemd-sysinstall** (introduced in systemd 261).
- The installer is **offline** — DDI embedded as a data partition. No network pull at install time.
- SSH in the live installer is exposed by `sshd.service`; the image pre-generates host keys so `ssh root@<ip>` works as soon as networking comes up.
- `just validate` is the merge contract for element graph changes.
