# Bluefin Server

**The world’s premier FSDK server operating system.**

Bluefin Server an operating system designed for modern workloads. The use case is the same as Flatcar Linux, Fedora CoreOS, and Talos. The difference is this is built with buildstream.API and GitOps driven.

## What it is

- FSDK-first server OS work in progress
- Image-based updates and atomic rollbacks
- GitOps-driven builds in the lab, no ssh, no apps, no bullshit, just git
- Pure DDI, follows modern linux patterns

## Build model

Use the local `just` targets while iterating:

```sh
just show-me-the-future
```

## Repository status

## Versioning

All versions just follow fsdk. Tags are derived from the pinned junction ref in
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
