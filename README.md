# Bluefin Server

**The world’s premier FSDK server operating system.**

Bluefin Server an operating system designed for modern workloads. The use case is the same as Flatcar Linux, Fedora CoreOS, and Talos. 

The difference is this is [DDI first](https://0pointer.net/blog/fitting-everything-together.html) and built with buildstream. API and GitOps driven. 

## What it is

- FSDK-first server OS work in progress
- Image-based updates and atomic rollbacks
- Fully automated GitOps-driven builds
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

GitHub Actions compiles the entire project (Standalone OS DDI and bootable installer) and handles publishing automatically. Automated Renovate manages updates to core platform dependencies.

| Trigger | Workflow / Job | What happens |
|---------|---------------|--------------|
| Pull request | `build.yml` | Resolves element graph (`just validate`) and executes raw BuildStream compilation to verify stability. Resolves/tracks Renovate refs automatically if opened by Renovate. |
| Push to `main`, `workflow_dispatch` | `build.yml` | Builds stand-alone DDI OS, live installer, and target UKI using `/mnt` SSD storage on GHA hosted runners, then creates/updates the corresponding GitHub Release and uploads all compiled assets. |

No PATs/App tokens/repository_dispatch are used; Renovate is the control driver.
See [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) for conventions.

## License

Apache-2.0.
