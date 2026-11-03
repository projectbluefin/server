<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-dark.svg">
</picture>

> Amargasaurus cazaui
>
> An image-based Linux server OS built like a container, composed from freedesktop-sdk.

Bluefin Server targets the same workload space as Flatcar Container Linux, Fedora CoreOS, and Talos. Built with [BuildStream 2](https://buildstream.build/), its userspace, kernel, and boot chain compose from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) (FSDK 26.08, systemd v261) components. No other distribution binaries ship in the base image; third-party userspace extensions (such as Flatcar System Extension Bakery images) require `systemd-sysext merge --force` per [systemd-sysext-extensions.md](docs/skills/systemd-sysext-extensions.md).

It is [DDI first](https://0pointer.net/blog/fitting-everything-together.html) and diskless-first: one build generates a verity-sealed `/usr`, signed UKIs, an OS DDI pulled into RAM over HTTP, and an offline USB installer. Rebooting updates diskless nodes; disk installation is optional.

> The only thing worse than a nightmare is a factory of nightmares that makes other nightmares

![armargasaurus](https://upload.wikimedia.org/wikipedia/commons/d/d8/Dicraeosauridae_Scale.svg)

## Release status: Alpha

Bluefin Server is currently in **Alpha**:
- **Trust model**: Every boot enforces Secure Boot (signed systemd-boot, signed UKIs, dm-verity `/usr` pinned by `usrhash=` on the command line). Releases include a GPG-signed `SHA256SUMS` manifest verified by `systemd-sysupdate` and initrd pull.
- **Suitability**: Alpha builds are intended for evaluation, testing, and factory validation. Not yet recommended for production workloads.
- **Roadmap**: Completed criteria and remaining gates toward 1.0 are tracked in [`docs/MVP_1_0_READINESS.md`](docs/MVP_1_0_READINESS.md).

## Architecture

- **Diskless boot** — Netboot UKI pulls `bluefin-server_<ver>.raw` into RAM with `rd.systemd.pull` (`verify=signature`), mounts a dm-verity erofs `/usr`, and runs from tmpfs. Nodes update by rebooting into a newer image, flagging `/run/reboot-required` when an updated image is offered. This is the recommended configuration for Kubernetes worker nodes.
- **Optional disk install with A/B rollback** — A running diskless node installs itself via [ddi-installer.md](docs/skills/ddi-installer.md) (`systemd-sysinstall` copies `/usr` into slot A). First disk boot creates slot B and an xfs root. `systemd-sysupdate` fills the inactive slot and reboots nightly (Kubernetes nodes defer reboots to kured); UKI boot counting automatically rolls back failed boots. Updates can be held via `/run/reboot-lock` or `/etc/reboot-lock`.
  - This is the recommended mode for Kubernetes Control Planes, and Home Servers.
- **Secure Boot by default** — Signed boot chain with `lockdown=integrity`. [Booty](https://github.com/jeefy/booty) serves UEFI HTTP boot assets and per-node Ignition configs.
- **Declarative provisioning** — Pass an `ignition.config` credential (or `bluefin-node.ign` next to the UKI); Ignition runs in the initrd on every boot. Configs must be idempotent.
- **Opt-in sysexts** — k0s, kubeadm, homelab automation, OpenZFS, and NVIDIA drivers/CDI ship as separate `systemd-sysext` images outside the base `/usr`.

> **Remote diagnostics:** OpenSSH is installed for diagnostics but disabled by default via presets. Start manually with `systemctl start sshd` when access is required. See [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).

## Installation Profiles

Choose your profile during installation. Start small and build up or go full lazy mode ootb. 

### Core and Kubernetes Profiles

| Boot Menu Option | Best For | Included Software | First Boot Login |
|---|---|---|---|
| **Bluefin Server** *(Default)* | Minimal servers and automated deployments | Base OS only (read-only system root, systemd, SSH). No container engines or Kubernetes. | Prompts on the local console (tty1) to set the root password. |
| **Homelab: Control Plane** | Primary node for a multi-machine Kubernetes cluster | Base OS + kubeadm, containerd, Argo Workflows, and a KubeStellar dashboard | Prompts on tty1 for a root password. Prints the cluster join passphrase on the screen. |
| **Homelab: Node** | Worker nodes joining an existing Homelab cluster | Base OS + kubeadm, containerd, and auto-join service. | Prompts for the cluster join passphrase during install; prompts on tty1 for a root password on first boot. |

### Home Server Profile

This is lazy mode, which includes `brew` for that lazy Ubuntu Server vibe. This mode is great for the home to run everything, or if you just need a box/VM that needs an OS to run one thing. Having brew baked in makes this perfect for VMs/machines to hold your agents/tmux, etc. 

| Boot Menu Option | Best For | Included Software | First Boot Login |
|---|---|---|---|
| **Bluefin Home Server** | Standalone personal server running containers and tools | Base OS + Podman (default) + Homebrew inside an isolated nspawn system container. Root stays locked. | Prompts on the local console to create a regular user account and password (or accepts an SSH key via credential). |

## Downloads

Each push to `main` publishes an immutable [GitHub Release](https://github.com/projectbluefin/server/releases) (`v<YY.MM.run>`) and an OCI artifact at `ghcr.io/projectbluefin/bluefin-server:<ver>`.

| File | Use case |
|---|---|
| `bluefin-server-netboot_<ver>.esp.raw` | Flash to USB for diskless HTTP boot (pulls OS into RAM). |
| `bluefin-server-installer_<ver>.raw` | Flash to USB for offline `systemd-sysinstall` to disk. |
| `bluefin-server_<ver>.raw` | OS DDI served by [Booty](https://github.com/jeefy/booty) for network boot at scale. |

The full release set (UKIs, sysexts, Ignition templates, SBOM) is defined in [`elements/oci/bluefin-server-image.bst`](elements/oci/bluefin-server-image.bst); `SHA256SUMS` lists every published file. Verify downloads against the GPG-signed `SHA256SUMS` using [`files/os/sysupdate-keys/import-pubring.gpg`](files/os/sysupdate-keys/import-pubring.gpg); see [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md).

### USB installation

Write `bluefin-server-installer_<ver>.raw` to a USB drive, configure UEFI Secure Boot Setup Mode, and boot the stick. Enroll Bluefin keys when prompted, select the target disk, and confirm. After reboot, set the console root password. Unattended installs, firmware warnings, and recovery details are in [`docs/skills/usb-installer.md`](docs/skills/usb-installer.md).

## Quick start

Local builds require `podman` and [`just`](https://github.com/casey/just). BuildStream runs containerized inside the FSDK `bst2` image:

```sh
just validate        # resolve element dependency graph
just export-image    # build release set into dist/diskless/
just dogfood-check   # headless QEMU diskless boot with Secure Boot
just dogfood-install # diskless boot, install to disk, verify rollback (QEMU)
```

## Documentation index

Start here to explore architecture and operations guides in [`docs/skills/`](docs/skills/index.md):

| Guide | Scope |
|---|---|
| [`ddi-installer.md`](docs/skills/ddi-installer.md) | Boot, installation, and A/B sysupdate lifecycle |
| [`usb-installer.md`](docs/skills/usb-installer.md) | Offline USB installer, interactive prompts, and unattended installs |
| [`booty-integration.md`](docs/skills/booty-integration.md) | UEFI HTTP boot, iPXE chainloading, and network boot provisioning |
| [`diskless-troubleshooting.md`](docs/skills/diskless-troubleshooting.md) | RAM sizing, initrd failure modes, and Ignition debugging |
| [`systemd-sysext-extensions.md`](docs/skills/systemd-sysext-extensions.md) | System extensions, bakery compatibility, and version locking |
| [`kubeadm-sysext.md`](docs/skills/kubeadm-sysext.md) | Kubeadm worker and single-node control-plane extensions |
| [`k0s-sysext-ops.md`](docs/skills/k0s-sysext-ops.md) | K0s cluster operations, tokens, and troubleshooting |
| [`homelab-profile.md`](docs/skills/homelab-profile.md) | Homelab Ignition templates, mDNS cluster join, and add-ons |
| [`nvidia-sysext.md`](docs/skills/nvidia-sysext.md) | NVIDIA open kernel modules and Container Toolkit CDI extensions |
| [`systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) | Release signatures, sysupdate policies, and SBOM attestations |
| [`secure-boot-keys.md`](docs/skills/secure-boot-keys.md) | Key enrollment, signing workflows, and shim integration |
| [`gap-analysis-distros.md`](docs/skills/gap-analysis-distros.md) | Comparison to Flatcar, Fedora CoreOS, Ubuntu, and Talos |

Complete manifest and developer commands are listed in [`AGENTS.md`](AGENTS.md) and [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Security and release trust

- **Signed boot chain**: ESP key enrollment runs on first boot. The installer halts if Secure Boot is disabled unless explicitly overridden; see [`docs/skills/secure-boot-keys.md`](docs/skills/secure-boot-keys.md).
- **Signed manifests & updates**: Builds emit signed `SHA256SUMS` manifests. Updates and initrd pulls verify signatures automatically (`Verify=yes`).
- **Attestations**: Releases publish SLSA provenance and SPDX SBOM attestations. Report vulnerabilities per [`SECURITY.md`](SECURITY.md).

## Further reading

- [Track progress and file issues](https://github.com/projectbluefin/server/issues)
- [Systemd Discoverable Disk Images Specification](https://uapi-group.org/specifications/specs/discoverable_disk_image/)
- Bare-metal deployments: [Knuckle](https://github.com/projectbluefin/knuckle) and the [Bluespeed](https://github.com/projectbluefin/bluespeed) homelab factory.

## License

Apache-2.0.
