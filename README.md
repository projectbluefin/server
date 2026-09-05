# Bluefin Server

**An FSDK-based, image-based Linux server OS.**

Bluefin Server targets the same use-case space as Flatcar Container Linux, Fedora CoreOS, and Talos, but is built from scratch with [BuildStream 2](https://buildstream.build/) from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) components.

It is [DDI first](https://0pointer.net/blog/fitting-everything-together.html): the OS payload is a compressed XFS DDI filesystem image that is deployed by an offline, systemd-native installer.

## What it is

- **Image-based updates and atomic rollbacks** via A/B partition slots and `systemd-sysupdate`.
- **DDI-first delivery** — the installer embeds the OS payload as a data partition; no network is required at install time.
- **Minimal, distroless OS image** — no shell in the running rootfs by default.
- **systemd-native installer** — `systemd-sysinstall` provides the interactive terminal UI and `systemd-repart` handles partitioning and block-copy DDI placement.
- **Podman in the base system** for running OCI containers without adding a package layer.
- **Optional k3s as a `systemd-sysext`** so Kubernetes stays separate from the base image.

> **SSH policy:** OpenSSH is installed but `sshd.service` is disabled by default and only accepts public-key authentication (`PasswordAuthentication no`, `PermitRootLogin prohibit-password`). Provision an authorized key through an external mechanism before running `systemctl enable --now sshd.service`; first-boot key provisioning is not implemented yet. See [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).

## Quick start

You need only `podman` and [`just`](https://github.com/casey/just). BuildStream runs inside the FSDK `bst2` container, so BuildStream is not installed locally.

```sh
just validate              # resolve the element graph
just test                  # install and boot-test locally in QEMU/KVM
```

See [`AGENTS.md`](AGENTS.md) for the full build matrix and agent skill routing.

## Enable Kubernetes

Bluefin Server ships Podman in the base image. Kubernetes is optional: provision
the published k3s `systemd-sysext` as `/var/lib/extensions/k3s.raw` (decompress the
release asset first if needed), then refresh extensions:

```sh
systemd-sysext refresh
systemd-sysext status
```

For a server node, create `/etc/rancher/k3s/config.yaml` with any required
settings, then enable k3s. The file may carry the cluster join token, so keep
it root-only (`0600`):

```yaml
# /etc/rancher/k3s/config.yaml
# token: set-a-shared-secret-for-agents
```

```sh
chmod 0600 /etc/rancher/k3s/config.yaml
systemctl enable --now k3s.service
```

For an agent node, configure the server URL and shared token instead:

```yaml
# /etc/rancher/k3s/config.yaml
server: https://control-plane.example:6443
token: set-a-shared-secret
```

```sh
chmod 0600 /etc/rancher/k3s/config.yaml
systemctl enable --now k3s-agent.service
```

Both units are disabled by default. Do not use the upstream `curl | sh`
installer; k3s is delivered and managed as a systemd sysext. See
[`docs/skills/k3s-sysext-ops.md`](docs/skills/k3s-sysext-ops.md) for extension
provisioning, OTA delivery, and troubleshooting.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contributor checklist and [`docs/skills/index.md`](docs/skills/index.md) for task-specific guidance.

## Release trust

- GitHub Actions builds all artifacts, signs a combined `SHA256SUMS` manifest, and publishes a GitHub Release.
- Updates are verified with GPG-signed `SHA256SUMS` manifests from GitHub Releases.
- See [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for the trust model.

## License

Apache-2.0.
