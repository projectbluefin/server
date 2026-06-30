# Bluefin Server

**The world’s premier FSDK server operating system.**

Bluefin Server is the private, image-based server track for Project Bluefin. It is built from freedesktop-sdk components, keeps the host immutable, and pushes everything non-essential into containers, GitOps, or other isolated tooling. The goal is simple: a server that stays out of your way, updates atomically, and remains reproducible enough to trust in production.

Bluefin Server borrows the Bluefin philosophy: hands-off by default, purposeful about what belongs on the base system, and opinionated about the 96% case. The difference is the audience — this tree is aimed at server operators who want cloud-native workflows, immutable infrastructure, and a clean operating-system boundary.

## What it is

- FSDK-first server OS work in progress
- Image-based updates and atomic rollbacks
- GitOps-driven builds in the lab
- Private repo during migration to `projectbluefin/server`

## Build model

The current tree still contains BuildStream scaffolding used to stage and validate server artifacts locally. That remains useful for development, but the canonical build path is moving to the lab through GitOps.

The lab already exposes a `bluefin-server-build-pipeline` WorkflowTemplate in `projectbluefin/testing-lab`; that is the build hook this repo should align with as the migration completes.
Build workflows emit `lab-build/<commit-sha>` tags so lab automation can build from immutable Git refs without cross-repo dispatch tokens.

Use the local `just` targets while iterating:

```sh
just validate
just build
just export
just build-installer
just export-installer
just build-ddi
just export-ddi
just show-me-the-future
```

## Repository status

## Versioning

There is no application version for a base image, so the version axis is the
FSDK release. Tags are derived from the pinned junction ref in
`elements/freedesktop-sdk.bst`:

- `:latest` -- rolling
- `:25.08` -- FSDK minor line
- `:25.08.13` -- FSDK point release (treated immutable)

Every image self-declares its base via `io.projectbluefin.fsdk.version` and
`io.projectbluefin.fsdk.ref` labels.

## Build locally

Requires `podman` and [`just`](https://github.com/caesar/just). BuildStream runs
inside the FSDK `bst2` container -- nothing to install.

    just validate        # resolve the element graph
    just build           # build + load ghcr.io/projectbluefin/base:latest
    just verify          # assert distroless + certs + tzdata
    just tags            # show derived tags

## CI / Release pipeline

GitHub is the **control plane only** — it emits immutable Git refs/tags as build signals.
All build compute and registry pushes happen inside the testing lab.

| Trigger | Workflow / Job | What happens |
|---------|---------------|--------------|
| Pull request | `build.yml` → `validate` | `just validate` resolves the element graph — no build, no push |
| Push to `main`, `workflow_dispatch` | `build.yml` → `trigger-lab` | Resolves HEAD SHA and publishes `lab-build/<sha>` tag |
| Daily **04:00 UTC** schedule | `lab-release.yml` → `dispatch-lab-build` | Resolves selected ref and publishes `lab-build/<sha>` tag |
| `workflow_dispatch` on `lab-release.yml` | `lab-release.yml` → `dispatch-lab-build` | Same as above; accepts optional `ref` input |
| Push tag `installer-v*` | `release-installer.yml` → `dispatch-lab-installer-build` | Resolves tag/SHA and publishes `installer-build/<installer-tag>` tag |
| `lab-build/*` and `installer-build/*` in testing-lab | testing-lab workflows | Lab builds artifacts and publishes to registry/releases |

No PATs/App tokens/repository_dispatch are used for build handoff; Git refs are the signal.
See [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) for conventions.

## License

Apache-2.0.
