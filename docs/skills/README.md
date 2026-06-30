---
name: skills-readme
description: Routing table for fsdk-containers skills. Load when onboarding to this repo or deciding which skill applies to your task.
metadata:
  type: index
---

# docs/skills — Routing

`fsdk-containers` brings distroless patterns to freedesktop-sdk (FSDK) containers.
Start at [AGENTS.md](../../AGENTS.md) for the project model and hard rules, then
load the focused skill for your task.

## Fast paths

| If your task is... | Load |
| ------------------ | ---- |
| Add a new distroless image (python, node, etc.) | [add-new-image.md](add-new-image.md) |
| Add a non-distroless nspawn machine image (dev env, tarball) | [nspawn-machine-image.md](nspawn-machine-image.md) |
| Build or debug the DDI live installer | [ddi-installer.md](ddi-installer.md) |
| Make an image smaller / apply the SLIM recipe | [slim-an-image.md](slim-an-image.md) |
| Move to a new FSDK release / retag | [bump-fsdk-version.md](bump-fsdk-version.md) |
| Prove an image is still distroless | [verify-distroless.md](verify-distroless.md) |
| Supply chain security (signing and SBOM) | [signing-and-sbom.md](signing-and-sbom.md) |
| Write or debug a CI workflow | [ci-tooling.md](ci-tooling.md) |
| Automate ArtifactHub submissions | [artifacthub-automation.md](artifacthub-automation.md) |
| Finishing a task (always) | [skill-improvement.md](skill-improvement.md) |

## What belongs here

Workflow knowledge and operational runbooks any agent needs to work in this repo.
**Not here:** agent-instruction files (`AGENTS.md`) — loaded separately by tools.

## Standing facts

- BuildStream runs in the FSDK `bst2` container via `just bst`. Nothing to install
  but `podman` + `just`.
- Compose from FSDK `components/*`, never `platform.bst`.
- Slim by default; keep tzdata + common charsets + CA certs.
- `just verify` (4 gates) is the merge contract.
