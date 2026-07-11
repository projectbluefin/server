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

## System containers

System containers are transparent, systemd-managed toolboxes you can turn on when you need them. They are meant to feel like part of the host, not like a separate app stack.

The first built-in examples are:

- `homebrew` for a Homebrew-based toolbox experience
- `ubuntu` for an Ubuntu-style server shell
- `debian` for a Debian-style toolbox

### First-time setup

Replace the placeholder image URL below with the published image you want to import.

```sh
sudo machinectl import-tar <homebrew-image-url> homebrew
sudo system-container start homebrew
sudo system-container enter homebrew
```

When you are done inside the container, leave it with `exit` and stop it again when you do not need it:

```sh
exit
sudo system-container stop homebrew
```

### Daily use

Use the same commands every day:

```sh
sudo system-container start homebrew
sudo system-container enter homebrew
```

To stop it later:

```sh
sudo system-container stop homebrew
```

If you want to see what is available on the host:

```sh
machinectl list
machinectl list-images
```

### Other containers

Ubuntu:

```sh
sudo machinectl import-tar <ubuntu-image-url> ubuntu
sudo system-container start ubuntu
sudo system-container enter ubuntu
```

Debian:

```sh
sudo machinectl import-tar <debian-image-url> debian
sudo system-container start debian
sudo system-container enter debian
```

### Reset a container

Resetting removes the machine and starts over from a fresh import:

```sh
sudo system-container reset homebrew
sudo machinectl import-tar <homebrew-image-url> homebrew
sudo system-container start homebrew
```

Homebrew uses `/home/linuxbrew` as the writable prefix and defaults to `HOMEBREW_NO_AUTO_UPDATE=1` and `HOMEBREW_NO_INSTALL_CLEANUP=1` so it behaves like a real Linux Homebrew environment. This is a convenience wrapper for daily use, not a security boundary.

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
