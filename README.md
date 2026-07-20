# Bluefin Server

**An FSDK-based, image-based Linux server OS.**

Bluefin Server targets the same use-case space as Flatcar Container Linux, Fedora CoreOS, and Talos, but is built from scratch with [BuildStream 2](https://buildstream.build/) from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) components.

It is [DDI first](https://0pointer.net/blog/fitting-everything-together.html): the OS payload is a compressed XFS DDI filesystem image that is deployed by an offline, systemd-native installer.

## What it is

- **Image-based updates and atomic rollbacks** via A/B partition slots and `systemd-sysupdate`.
- **DDI-first delivery** — the installer embeds the OS payload as a data partition; no network is required at install time.
- **Minimal, distroless OS image** — no shell in the running rootfs by default.
- **systemd-native installer** — `systemd-sysinstall` provides the interactive terminal UI and `systemd-repart` handles partitioning and block-copy DDI placement.
- **Optional k3s as a `systemd-sysext`** so the base image stays distroless.

> **Temporary bring-up exception:** SSH is enabled for cluster boot tests and remote debugging. It is scheduled for removal once diagnostics move to serial logs or a guest agent. See [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).

## Quick start

You need only `podman` and [`just`](https://github.com/casey/just). BuildStream runs inside the FSDK `bst2` container, so BuildStream is not installed locally.

```sh
just validate              # resolve the element graph
just show-me-the-future    # end-to-end QEMU installer smoke test
```

See [`AGENTS.md`](AGENTS.md) for the full build matrix and agent skill routing.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contributor checklist and [`docs/skills/INDEX.md`](docs/skills/INDEX.md) for task-specific guidance.

## Release trust

- GitHub Actions builds all artifacts, signs a combined `SHA256SUMS` manifest, and publishes a GitHub Release.
- Updates are verified with GPG-signed `SHA256SUMS` manifests from GitHub Releases.
- See [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for the trust model.

## License

Apache-2.0.
