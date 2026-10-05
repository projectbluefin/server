<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-light.svg">
  <img alt="Bluefin Server" src="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-light.svg" width="400">
</picture>

> Amargasaurus cazaui

**An image-based Linux server OS built like a container, composed from freedesktop-sdk.**

Bluefin Server targets the same use-case space as Flatcar Container Linux, Fedora CoreOS, and Talos, and is built with [BuildStream 2](https://buildstream.build/). Its entire userspace, kernel, and boot chain compose from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) (FSDK 26.08, systemd v261) components. No other distro's binaries ship in the image.

It is [DDI first](https://0pointer.net/blog/fitting-everything-together.html) and diskless-first: one build produces a verity-sealed `/usr` image, signed UKIs, an OS DDI that a node pulls into RAM over HTTP, and an offline USB installer. Rebooting is how a diskless node updates. Installing to disk is optional.

> The only thing worse than a nightmare is a factory of nightmares that makes other nightmares

![armargasaurus](https://upload.wikimedia.org/wikipedia/commons/d/d8/Dicraeosauridae_Scale.svg)

## Release status: Alpha

Bluefin Server is currently in **Alpha**:
- **Trust model**: every boot is Secure Boot verified end to end (signed systemd-boot, signed UKIs, dm-verity `/usr` pinned by `usrhash=` on the locked kernel command line). The release set carries a GPG-signed `SHA256SUMS` manifest that both `systemd-sysupdate` and the diskless pull verify.
- **Suitability**: Alpha builds are intended for evaluation, testing, and factory validation. Not yet recommended for production workloads.
- **Readiness roadmap**: Track completed criteria and remaining gates toward 1.0 in [`docs/MVP_1_0_READINESS.md`](docs/MVP_1_0_READINESS.md).

## What it is

- **Diskless-first boot** — the netboot UKI pulls `bluefin-server_<ver>.raw` into RAM with `rd.systemd.pull`, verified against the signed `SHA256SUMS` (`verify=signature`), mounts a dm-verity erofs `/usr`, and runs from tmpfs. A diskless node updates by rebooting into a newer image, and flags `/run/reboot-required` when its boot server offers one that its next boot would pull (not when the node is pinned to a versioned image).
- **Optional disk install with A/B rollback** — a running diskless node *is* the installer: see [ddi-installer.md](docs/skills/ddi-installer.md) (`systemd-sysinstall` copies `/usr` into slot A). The first disk boot creates slot B and a persistent xfs root. `systemd-sysupdate` fills the inactive slot on a timer and reboots into it nightly (Kubernetes nodes leave the reboot to kured), and UKI boot counting rolls back an update that does not boot cleanly: a boot-counted boot that has not reached `boot-complete.target` (any failed unit counts) within 15 minutes reboots, or on Kubernetes nodes is flagged for kured, until systemd-boot falls back to the previous image, which then stays put until a newer release. `/run/reboot-lock` or `/etc/reboot-lock` holds these reboots.
- **Secure Boot on** — signed systemd-boot, signed UKIs, signed kernel modules, `lockdown=integrity`. UEFI HTTP boot is supported; [Booty](https://github.com/jeefy/booty) serves the UKI, the OS DDI, the signed manifest, and a per-node `bluefin-node.ign`.
- **Opt-in per-node state via Ignition** — pass an `ignition.config` / `ignition.config.url` system credential (or, on UEFI HTTP boot, a `bluefin-node.ign` next to the UKI) and Ignition runs in the initrd on every boot; configs must be idempotent.
- **Opt-in sysexts** — k0s (Kubernetes), kubeadm, the homelab component set and its add-ons (Argo Workflows, a Kubernetes MCP server, KubeStellar), OpenZFS, the NVIDIA driver (open kernel modules) and the NVIDIA Container Toolkit ship as separate `systemd-sysext` images, never in the base `/usr`. The image-locked ones (ZFS, kubeadm, homelab and add-ons, NVIDIA driver) follow OS updates through optional sysupdate features.

> **Remote diagnostics:** OpenSSH is installed for on-demand diagnostics, but is disabled by default via systemd presets. It can be started manually with `systemctl start sshd` when remote access is needed. See [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).

## Download a release

Each push to `main` publishes an immutable [GitHub Release](https://github.com/projectbluefin/server/releases) tagged `v<YY.MM.run>` and the same file set as an OCI artifact at `ghcr.io/projectbluefin/bluefin-server` (tags `<ver>` and `latest`). Which file you want:

| File | Use it for |
|---|---|
| `bluefin-server-netboot_<ver>.esp.raw` | Written to a USB stick, boots a node diskless (pulls the OS into RAM over HTTP). |
| `bluefin-server-installer_<ver>.raw` | Written to a USB stick, boots into `systemd-sysinstall` for an offline install to disk. |
| everything else | [Booty](https://github.com/jeefy/booty) syncs the whole release and serves it for network boot at scale. |

Verify the download against the GPG-signed `SHA256SUMS` before use; the release public keyring is [`files/os/sysupdate-keys/import-pubring.gpg`](files/os/sysupdate-keys/import-pubring.gpg), and the verification and attestation steps are in [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md).

### Install from the USB stick

Secure Boot is required. Write `bluefin-server-installer_<ver>.raw` to a USB stick, put the machine's firmware into Secure Boot **Setup Mode**, boot the stick, and choose **Enroll the Bluefin Server keys and restart** when the installer offers it; after the restart it installs with Secure Boot on. If Secure Boot is off or the firmware trusts other keys, the installer stops before touching any disk and shows what to change in the firmware; installing anyway needs an explicit **Continue without Secure Boot**. The firmware steps, what the warning means and unattended installs are in [`docs/skills/usb-installer.md`](docs/skills/usb-installer.md) ("Secure Boot").
The installer then lists the disks with their size and model: type the number of the disk to install to and confirm with `yes`. It says when the install is done and restarts; remove the stick when the screen goes blank. The first start asks on the screen for a root password, then you log in as root at the console; the login banner shows the node's hostname and IP address ([`docs/skills/usb-installer.md`](docs/skills/usb-installer.md), "Using the installer").

## Quick start

You need only `podman` and [`just`](https://github.com/casey/just). BuildStream runs inside the FSDK `bst2` container, so BuildStream is not installed locally.

```sh
just validate        # resolve the element graph
just export-image    # build the release set into dist/diskless/
just dogfood-check   # headless QEMU diskless boot with Secure Boot
just dogfood-install # diskless boot, install to disk, boot it (QEMU)
```

For network boot at scale, [Booty](https://github.com/jeefy/booty) syncs a
release (from GitHub or the OCI artifact) and HTTP-boots nodes with per-host
Ignition and optional `doInstall` to disk.

See [`AGENTS.md`](AGENTS.md) for the full build command matrix, hard rules, and agent skill routing.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contributor checklist, Conventional Commit rules, and [`docs/skills/index.md`](docs/skills/index.md) for task-specific guidance.

## Security and release trust

- **Signed boot chain**: Secure Boot keys enroll from the ESP on first boot (`secure-boot-enroll if-safe` in VMs; on bare metal in firmware Setup Mode, from the USB installer's prompt or the systemd-boot menu); the USB installer refuses to install without Secure Boot on with these keys unless told explicitly. Local builds use throwaway Secure Boot keys from `just gen-dev-keys`, with the published INSECURE dev module signing key from `files/dev-keys/` (never in a release; see [`docs/skills/secure-boot-keys.md`](docs/skills/secure-boot-keys.md)).
- **Signed manifests**: the build signs one combined `SHA256SUMS` over the whole image set (OS images, UKIs, sysexts) inside `oci/bluefin-server-image.bst`; a release publishes `dist/diskless/` as-is to GitHub Releases and as an OCI artifact.
- **Sysupdate verification**: installed nodes verify updates against the signed manifest (`Verify=yes`), and the diskless pull checks the same signature in the initrd; see [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for details.
- **Provenance and SBOM**: releases carry SLSA provenance and SPDX SBOM attestations; see [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for verification.
- **Vulnerability disclosure**: See [`SECURITY.md`](SECURITY.md) for policy details and how to report security issues.

## Further reading

- [Track progress and file issues](https://github.com/projectbluefin/server/issues)
- [Systemd Discoverable Disk Images Specification](https://uapi-group.org/specifications/specs/discoverable_disk_image/)
- Bare-metal Flatcar deployments: [Knuckle](https://github.com/projectbluefin/knuckle) and the [Bluespeed](https://github.com/projectbluefin/bluespeed) homelab factory.

## License

Apache-2.0.
