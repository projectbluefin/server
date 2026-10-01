<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-dark.svg">
  <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-light.svg">
  <img alt="Bluefin Server" src="https://raw.githubusercontent.com/projectbluefin/artwork/main/assets/vector/logos/bluefin-server/bluefin-server-logo-light.svg" width="400">
</picture>

> Amargasaurus cazaui

**An image-based Linux server OS built like a container, composed from freedesktop-sdk.**

Bluefin Server targets the same use-case space as Flatcar Container Linux, Fedora CoreOS, and Talos, and is built with [BuildStream 2](https://buildstream.build/). Its base userspace, kernel, and boot chain compose from [freedesktop-sdk](https://freedesktop-sdk.freedesktop.org/) (FSDK 26.08, systemd v261) components. No other distro's binaries ship in the base image; compatible [Flatcar System Extension Bakery images](docs/skills/systemd-sysext-extensions.md) are encouraged as optional userspace extensions.

The normal product is the native USB installation with the Complete profile: the same verity-sealed FSDK OS plus separately signed runtime and homelab payloads. Core is an advanced builder choice, not a second OS build or update channel. The netboot UKI and OS DDI retain their diskless-first behavior without implicitly enabling a controller on existing installations.

> The only thing worse than a nightmare is a factory of nightmares that makes other nightmares

![armargasaurus](https://en.wikipedia.org/wiki/Amargasaurus#/media/File:Dicraeosauridae_Scale.svg)

## Release status: Alpha

Bluefin Server is currently in **Alpha**:
- **Trust model**: every boot is Secure Boot verified end to end (signed systemd-boot, signed UKIs, dm-verity `/usr` pinned by `usrhash=` on the locked kernel command line). The release set carries a GPG-signed `SHA256SUMS` manifest that both `systemd-sysupdate` and the diskless pull verify.
- **Suitability**: Alpha builds are intended for evaluation, testing, and factory validation. Not yet recommended for production workloads.
- **Readiness roadmap**: Track criteria toward 1.0 in [`docs/MVP_1_0_READINESS.md`](docs/MVP_1_0_READINESS.md). The integrated Complete profile is a release candidate until the native installer, browser, worker, offline, update and recovery proofs pass; source/unit checks alone are not that evidence.

## Local-first by design

[Local-first is a project primitive](docs/skills/server-profile.md). The appliance uses pinned upstream images rather than custom Console/Argo forks. Stock Console does not meet the planned local-owner account flow; supported authentication and other explicit acceptance gaps are recorded in the canonical contract, not hidden behind a development-login bypass.

## What it is

- **Diskless-first boot** — the netboot UKI pulls `bluefin-server_<ver>.raw` into RAM with `rd.systemd.pull`, verified against the signed `SHA256SUMS` (`verify=signature`), mounts a dm-verity erofs `/usr`, and runs from tmpfs. A diskless node updates by rebooting into a newer image, and flags `/run/reboot-required` when its boot server offers one that its next boot would pull (not when the node is pinned to a versioned image).
- **Optional disk install with A/B rollback** — a running diskless node *is* the installer: see [ddi-installer.md](docs/skills/ddi-installer.md) (`systemd-sysinstall` copies `/usr` into slot A). The first disk boot creates slot B and a persistent xfs root. `systemd-sysupdate` fills the inactive slot on a timer and reboots into it nightly (Kubernetes nodes leave the reboot to kured), and UKI boot counting rolls back an update that does not boot cleanly: a boot-counted boot that has not reached `boot-complete.target` (any failed unit counts) within 15 minutes reboots, or on Kubernetes nodes is flagged for kured, until systemd-boot falls back to the previous image, which then stays put until a newer release. `/run/reboot-lock` or `/etc/reboot-lock` holds these reboots.
- **Secure Boot on** — signed systemd-boot, signed UKIs, signed kernel modules, `lockdown=integrity`. UEFI HTTP boot is supported; [Booty](https://github.com/jeefy/booty) serves the UKI, the OS DDI, the signed manifest, and a per-node `bluefin-node.ign`.
- **Opt-in per-node state via Ignition** — pass an `ignition.config` / `ignition.config.url` system credential (or, on UEFI HTTP boot, a `bluefin-node.ign` next to the UKI) and Ignition runs in the initrd on every boot; configs must be idempotent.
- **Separately delivered runtime** — Complete selects pinned Flatcar Kubernetes/containerd extensions and the Server support extension; they never enter the base `/usr`. Core leaves runtime inactive.
- **Opt-in sysexts** — k0s (Kubernetes), KubeStellar, kubeadm, OpenZFS, the NVIDIA driver (open kernel modules) and the NVIDIA Container Toolkit ship as separate `systemd-sysext` images, never in the base `/usr`, and remain separate from the Complete runtime. The image-locked ones (ZFS, KubeStellar, kubeadm, NVIDIA driver) follow OS updates through optional sysupdate features.

> **Remote diagnostics:** OpenSSH is installed for on-demand diagnostics, but is disabled by default via systemd presets. It can be started manually with `systemctl start sshd` when remote access is needed. See [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md).

## Download a release

Each push to `main` publishes an immutable [GitHub Release](https://github.com/projectbluefin/server/releases) tagged `v<YY.MM.run>` and the same file set as an OCI artifact at `ghcr.io/projectbluefin/bluefin-server` (tags `<ver>` and `latest`). Which file you want:

| File | Use it for |
|---|---|
| `bluefin-server-installer_<ver>.raw` | Normal USB installation; Complete is default, Core is the optional builder profile. |
| `bluefin-server-netboot_<ver>.esp.raw` | Advanced diskless boot; pulls the minimal OS into RAM over HTTP. |
| `bluefin-server_<ver>.raw` | Advanced Core DDI; also the existing diskless installation payload. |
| `server-bundle_<ver>.tar.zst` | Coherent signed Complete payload transport; not an OS installer or a runtime binary-swap instruction. |
| everything else | The signed release inventory, boot artifacts, runtime payloads and provenance consumed by provisioning and update tools. |

Verify the download against the GPG-signed `SHA256SUMS` before use; the release public keyring is [`files/os/sysupdate-keys/import-pubring.gpg`](files/os/sysupdate-keys/import-pubring.gpg), and the verification and attestation steps are in [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md).

## Install and use

1. Verify the USB installer, write it to a spare USB device, and boot it. Complete is profile `@0`; the native boot menu offers Core for builders as `@1`.
2. Select the target disk and confirm its erasure in stock `systemd-sysinstall`. Complete does not ask for an OS root password; Core asks on first disk boot (see [usb-installer.md](docs/skills/usb-installer.md)).
3. Complete brings up its standalone cluster and pinned platform. Initial
   container acquisition needs upstream registries unless images are cached.
4. Stock Console is optional and stays inactive until its supported upstream
   authentication is configured privately. It remains ClusterIP-only; there is
   no custom owner claim, browser Add Node or physical account-recovery API in
   the stock image.

Workers use private kubeadm provisioning rather than a public installer token
or the removed fork's browser pairing. A worker adds capacity, not control-plane
HA. Runtime updates preserve native transaction/rollback boundaries; an OS
rollback is not an etcd rollback. Single-node maintenance has downtime. See
[server-profile.md](docs/skills/server-profile.md) for current access limitations.

## Build and verify locally

BuildStream runs inside the FSDK `bst2` container using `podman` and [`just`](https://github.com/casey/just). The platform snapshot uses tracked manifests with Git/Python inside that build; application binaries/images come from upstream. No host npm, Console/Argo source compilation or Helm invocation is required. Optional disposable compatibility proof is separate from graph validation.

```sh
just validate                # version checks + graph only; no application builds
just export-image            # assemble the signed appliance release
just test-unit               # existing consumer checks
just prepare-server          # inspect the stock manifest/Git baseline
just verify-server-platform  # explicit optional disposable compatibility proof
just dogfood-check           # advanced Core diskless boot with Secure Boot
```

For network boot at scale, [Booty](https://github.com/jeefy/booty) syncs a
release (from GitHub or the OCI artifact) and HTTP-boots nodes with per-host
Ignition and optional `doInstall` to disk.

See [`AGENTS.md`](AGENTS.md) for the full build command matrix, hard rules, and agent skill routing.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for the contributor checklist, Conventional Commit rules, and [`docs/skills/index.md`](docs/skills/index.md) for task-specific guidance.

## Security and release trust

- **Signed boot chain**: Secure Boot keys enroll from the ESP on first boot (`secure-boot-enroll if-safe` in VMs, or manually via systemd-boot menu in firmware Setup Mode on bare metal); local builds use throwaway keys from `just gen-dev-keys`.
- **Signed manifests**: the build signs one combined `SHA256SUMS` over the whole image set (OS images, UKIs, sysexts) inside `oci/bluefin-server-image.bst`; a release publishes `dist/diskless/` as-is to GitHub Releases and as an OCI artifact.
- **Sysupdate verification**: installed nodes verify updates against the signed manifest (`Verify=yes`), and the diskless pull checks the same signature in the initrd; see [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for details.
- **Provenance and SBOM**: releases carry SLSA provenance and SPDX SBOM attestations; see [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) for verification.
- **Vulnerability disclosure**: See [`SECURITY.md`](SECURITY.md) for policy details and how to report security issues.

## License

Apache-2.0.
