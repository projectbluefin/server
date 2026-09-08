# Bluefin Server
> Amargasaurus cazaui

**An FSDK-based, image-based Linux server OS.**

Bluefin Server targets the same use-case space as Flatcar Container Linux, Fedora CoreOS, and Talos, but is built from scratch with [BuildStream 2](https://buildstream.build/) from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) (FSDK 26.08) components and uutils coreutils.

It is [DDI first](https://0pointer.net/blog/fitting-everything-together.html): the OS payload is a compressed XFS DDI filesystem image that is deployed by an offline, systemd-native installer.

> The only thing worse than a nightmare is a factory of nightmares that makes other nightmares

![armargasaurus](https://en.wikipedia.org/wiki/Amargasaurus#/media/File:Dicraeosauridae_Scale.svg)

## Release status: Alpha

Bluefin Server is currently in **Alpha**:
- **Milestone status**: Phase A (reproducible build path, uutils, k0s sysext, graph validation) is complete. Phase B (automated boot verification on lab cluster) is in progress.
- **Trust model**: Releases include cryptographic provenance with GPG-signed `SHA256SUMS` manifests and in-tree `systemd-sysupdate` verification configurations.
- **Suitability**: Alpha builds are intended for evaluation, testing, and factory validation. Not yet recommended for production workloads.
- **Readiness roadmap**: Track completed criteria and remaining gates toward 1.0 in [`docs/MVP_1_0_READINESS.md`](docs/MVP_1_0_READINESS.md).

## What it is

- **Image-based updates and atomic rollbacks** via A/B partition slots and `systemd-sysupdate`.
- **DDI-first delivery** — the installer embeds the OS payload as a data partition; no network is required at install time.
- **Minimal, distroless OS image** — no shell in the running rootfs by default.
- **systemd-native installer** — `systemd-sysinstall` provides the interactive terminal UI and `systemd-repart` handles partitioning and block-copy DDI placement.
- **Optional k0s as a `systemd-sysext`** so the base image stays distroless.

> **Temporary bring-up exception:** SSH is enabled for cluster boot tests and remote debugging. It is scheduled for removal once diagnostics move to serial logs or a guest agent. See [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).

## Quick start

You need only `podman` and [`just`](https://github.com/casey/just). BuildStream runs inside the FSDK `bst2` container, so BuildStream is not installed locally.

```sh
just validate              # resolve the element graph
just show-me-the-future    # end-to-end QEMU installer smoke test
```

See [`AGENTS.md`](AGENTS.md) for the full build command matrix, hard rules, and agent skill routing.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contributor checklist, Conventional Commit rules, and [`docs/skills/index.md`](docs/skills/index.md) for task-specific guidance.

## Security and release trust

- **Signed manifests**: GitHub Actions builds all release artifacts, generates a combined `SHA256SUMS` manifest, and signs it with GPG before publishing to GitHub Releases.
- **Sysupdate verification**: Target nodes verify updates using signed manifest transfers; see [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for details.
- **Vulnerability disclosure**: See [`SECURITY.md`](SECURITY.md) for policy details and how to report security issues.

## License

Apache-2.0.
