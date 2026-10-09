---
name: gap-analysis-distros
description: |
  Source-verified gap analysis comparing Bluefin Server to Ubuntu Server, Talos Linux,
  Flatcar Container Linux, and Fedora CoreOS.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-08"
---
# Gap Analysis: Bluefin Server versus Comparable Server OSes

This is a source-verified, self-contained comparison using generic, public-facing framing.
Facts about other distributions are drawn from their upstream documentation;
facts about Bluefin Server are drawn from source files in this repository.

## 1. Comparison Axes

| Axis | What it covers |
|------|----------------|
| **Philosophy / use-case** | General-purpose vs. appliance; target workloads; API vs. package-centric management. |
| **Root filesystem mutability and state model** | Writable vs. read-only `/usr`; what persists across reboots/updates. |
| **Update mechanism and atomic rollback** | How OS images are delivered, staged, verified, rolled back. |
| **Provisioning / first-boot config** | How an unattended or first-boot configuration reaches the machine. |
| **Customization / extension model** | How users add software without rebuilding the base image. |
| **Reboot / rolling-update coordination** | How cluster-wide reboots are serialized or scheduled during updates. |

## 2. Current State of Each Comparison Distro

### Ubuntu Server

- **Philosophy:** General-purpose LTS server distribution (5 years standard support, extendable to 10 years through Pro) for a broad range of workloads and hardware.
  Source: [Ubuntu release lifecycle](https://ubuntu.com/about/release-cycle), [Server documentation](https://documentation.ubuntu.com/server/).
- **State model:** Fully mutable dpkg/apt-based system: root filesystem, `/usr`, package databases, and installed packages can all be modified in place.
- **Updates:** Package-level updates via `apt`; major releases via `do-release-upgrade`; optional automatic security updates through `unattended-upgrades`.
  Release upgrades can leave the system in a partially upgraded state and are generally not atomic.
  Sources: [automatic-updates.md](https://raw.githubusercontent.com/canonical/ubuntu-server-documentation/main/docs/how-to/software/automatic-updates.md), [upgrade-your-release.md](https://raw.githubusercontent.com/canonical/ubuntu-server-documentation/main/docs/how-to/software/upgrade-your-release.md).
- **Provisioning:** `cloud-init` on first boot for cross-platform initialization; the Ubuntu Server installer supports `autoinstall` for unattended installs.
  Sources: [cloud-init docs](https://cloudinit.readthedocs.io/), [autoinstall intro](https://canonical-subiquity.readthedocs-hosted.com/en/latest/intro-to-autoinstall.html).
- **Customization:** Native package installation with `apt`, PPAs, snaps, and conventional configuration management.
  Source: [package-management.md](https://raw.githubusercontent.com/canonical/ubuntu-server-documentation/main/docs/how-to/software/package-management.md).
- **Reboot coordination:** `unattended-upgrades` can reboot after updates; cluster-wide coordination is external (Landscape, MAAS, config-management playbooks, or operator process). There is no built-in cluster lock manager.

### Talos Linux

- **Philosophy:** Kubernetes-only appliance OS, API-managed, immutable, minimal, and secure-by-default.
  It is explicitly not a general-purpose Linux distribution.
  Source: [What is Talos Linux?](https://docs.siderolabs.com/talos/v1.13/overview/what-is-talos.md).
- **State model:** The root filesystem is a read-only SquashFS plus ephemeral tmpfs directories; persistent cluster state (etcd data, certificates) lives on `/var`.
  Source: [What is Talos Linux?](https://docs.siderolabs.com/talos/v1.13/overview/what-is-talos.md).
- **Updates:** Image-based A/B upgrades triggered through the Talos API (`talosctl upgrade`). The previous OS image is retained so a failed boot rolls back automatically and a manual rollback is possible via the API.
  Source: [Upgrading Talos Linux](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/lifecycle-management/upgrading-talos.md).
- **Provisioning:** A single declarative YAML machine configuration is supplied at install/boot time and applied through the Talos API; the OS does not use Ignition or cloud-init.
  Source: [Machine configuration overview](https://docs.siderolabs.com/talos/v1.13/reference/configuration/overview.md).
- **Customization:** Limited to official or custom system extensions baked into the installer/boot assets (ISO, PXE, disk image, installer container image); conventional package installation is not supported.
  Source: [System Extensions](https://docs.siderolabs.com/talos/v1.13/build-and-extend-talos/custom-images-and-development/system-extensions.md).
- **Reboot coordination:** Talos itself is Kubernetes-aware: the upgrade API drains/cordons a node and reboots it. Fleet orchestration is typically handled by `talosctl`, Omni, or a cluster template.
  No third-party reboot daemon such as Kured is required.
  Source: [Upgrading Talos Linux](https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/lifecycle-management/upgrading-talos.md).

### Flatcar Container Linux

- **Philosophy:** Minimal, declarative, container-optimized host focused on secure, automatically updated backend infrastructure.
  Source: [Update and reboot strategies](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/setup/releases/update-strategies.md).
- **State model:** `/usr` is mounted read-only from the active root partition; `/etc` and `/var` are writable and persistent across reboots.
  Source: [Ignition documentation](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/provisioning/ignition/_index.md).
- **Updates:** Dual-slot A/B root partitions managed by `update-engine`. Updates are downloaded to the passive partition and activated by rebooting into it; rollback is possible by selecting the previous partition.
  Source: [Update and reboot strategies](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/setup/releases/update-strategies.md).
- **Provisioning:** Ignition, authored through Butane, runs once in the initramfs on first boot to partition disks, create users, write files, and enable systemd units.
  Source: [Ignition documentation](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/provisioning/ignition/_index.md).
- **Customization:** Runtime extension via `systemd-sysext` overlays from the Flatcar System Extension Bakery; the `/usr` tree is otherwise immutable.
  Source: [Systemd-sysext](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/provisioning/sysext/_index.md).
- **Reboot coordination:** `locksmithd` is the default reboot manager (`etcd-lock`, `reboot`, or `off` strategies with maintenance windows). For Kubernetes clusters, FLUO or Kured are recommended over `locksmithd`.
  Source: [Update and reboot strategies](https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/setup/releases/update-strategies.md).

### Fedora CoreOS

- **Philosophy:** Automatically updating, minimal, monolithic, container-focused OS designed for clusters but usable standalone.
  Source: [Fedora CoreOS documentation](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/index.adoc).
- **State model:** `/usr` is immutable through OSTree deployments; `/etc` and `/var` are writable and persist across updates. `rpm-ostree` keeps the previous deployment for rollback.
  Source: [rpm-ostree README](https://raw.githubusercontent.com/coreos/rpm-ostree/main/README.md), [Fedora CoreOS FAQ](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/faq.adoc).
- **Updates:** Continuous auto-updates via `Zincati` + `rpm-ostree`. Zincati talks to Cincinnati for phased rollouts, stages a new OSTree deployment, and reboots when configured. Rollback is done by selecting the previous deployment at boot.
  Sources: [Auto-updates](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/auto-updates.adoc), [Zincati](https://coreos.github.io/zincati/).
- **Provisioning:** Ignition, authored through Butane, customizes a generic disk image on first boot; there is no separate install disk.
  Source: [Producing an Ignition Config](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/producing-ign.adoc).
- **Customization:** Containers are the preferred extension mechanism; `rpm-ostree` package layering is deprecated/discouraged for most uses. A large portion of system configuration is delivered as systemd units running containers, including via Podman Quadlet.
  Sources: [running-containers.adoc](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/running-containers.adoc), [FAQ](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/faq.adoc).
- **Reboot coordination:** Zincati supports immediate reboot, maintenance windows, and cluster-wide lock-based coordination via the FleetLock protocol.
  Sources: [Auto-updates](https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/auto-updates.adoc), [FleetLock protocol](https://coreos.github.io/zincati/development/fleetlock/).

## 3. Bluefin Server Current Implementation

Bluefin Server is a BuildStream 2-based, image-based Linux server OS composed
entirely from freedesktop-sdk (FSDK) 26.08 components (systemd v261, FSDK
kernel). No other distribution's binaries ship in the image.

| Axis | Bluefin Server (as-implemented) |
|------|---------------------------------|
| **Philosophy** | Systemd-native, minimal, image-based server OS; diskless-first (a node boots from a network-pulled image in RAM and updates by rebooting), with an optional disk install. Base /usr includes bash for login and bring-up while heavy developer/debug tools live in sysexts or system containers; container workloads and Kubernetes run via opt-in sysexts. Sources: [AGENTS.md](../../AGENTS.md), [factory-integration.md](factory-integration.md). |
| **State model** | `/usr` is a read-only erofs filesystem verified by dm-verity, pinned by `usrhash=` on the locked UKI command line. `/etc` is populated from `/usr/share/factory/etc` by systemd-tmpfiles: empty on every boot on a diskless (tmpfs) node, persistent across A/B updates on an installed node. Diskless nodes run from tmpfs. Installed nodes get a persistent xfs root via systemd gpt-auto discovery. Sources: [bluefin-server-usr.bst](../../elements/oci/bluefin-server-usr.bst), [bluefin-server-boot.bst](../../elements/oci/bluefin-server-boot.bst), [50-root.conf](../../files/os/repart.d/50-root.conf). |
| **Updates** | Installed nodes: `systemd-sysupdate` fills the inactive usr / usr-verity slot (`files/os/sysupdate.d/10-usr.transfer`, `11-usr-verity.transfer`) and installs the new disk UKI with boot counting (`20-uki.transfer`), so a failed update rolls back automatically. Assets are published to GitHub Releases and as an OCI artifact; the combined `SHA256SUMS` manifest covering the whole set is signed inside the image build (`oci/bluefin-server-image.bst`) and `Verify=yes` is the default. `systemd-sysupdate.timer` is enabled by preset, and `systemd-boot-check-no-failures.service` gates `boot-complete.target`, so an update is blessed only when no unit failed; `bluefin-boot-deadline.timer` reboots a counted boot that is not blessed in 15 minutes so systemd-boot falls back, and `bluefin-update-pending` keeps a rolled-back node off the failed version. Diskless nodes update by rebooting into a newer image (sysupdate is disabled when booted diskless); `bluefin-diskless-update-check` flags `/run/reboot-required` when the boot server offers a newer signed release that the next boot would pull (not for a node pinned to a versioned image). Sources: [ddi-installer.md](ddi-installer.md), [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md), [10-usr.transfer](../../files/os/sysupdate.d/10-usr.transfer), [20-uki.transfer](../../files/os/sysupdate.d/20-uki.transfer), [80-bluefin-updates.preset](../../files/os/systemd/system-preset/80-bluefin-updates.preset), [10-diskless.conf](../../files/os/systemd/system/systemd-sysupdate.service.d/10-diskless.conf), also `systemd-sysupdate(8)`. |
| **Provisioning** | Stock `systemd-sysinstall` copies `/usr` onto a target disk, started either from the offline USB installer (`bluefin-server-installer_<ver>.raw`) or on a diskless-booted node (see [ddi-installer.md](ddi-installer.md)). Per-node configuration is opt-in via Ignition, delivered as `ignition.config` / `ignition.config.url` system credentials (the cmdline is locked inside the signed UKI); Ignition runs on every boot, so configs must be idempotent. First-boot systemd credentials also cover root password, `tmpfiles.extra`, `network.*`, and `firstboot.*`. Sources: [bluefin-server-image.bst](../../elements/oci/bluefin-server-image.bst), [initrd-ignition.bst](../../elements/bluefin-server/initrd/initrd-ignition.bst), [os-creds-prov.bst](../../elements/bluefin-server/os-creds-prov.bst), [tpm2-credential-sealing.md](tpm2-credential-sealing.md). |
| **Customization** | Adds software through opt-in `systemd-sysext` images (overlay `/usr`): k0s (Kubernetes) and OpenZFS are built in-tree. The base OS `os-release` identifies as `ID=bluefin-server`; the ZFS sysext pins `VERSION_ID` to the image version because its kernel modules are built against the exact FSDK kernel. Sources: [systemd-sysext-extensions.md](systemd-sysext-extensions.md), [k0s-sysext.md](k0s-sysext.md), [os-release.bst](../../elements/bluefin-server/os-release.bst), [systemd-sysext(8)](https://www.freedesktop.org/software/systemd/man/latest/systemd-sysext.html). |
| **Reboot coordination** | `systemd-sysupdate-reboot.timer` reboots installed nodes into a staged update in a nightly window. `/run/reboot-lock` (until the next boot) or `/etc/reboot-lock` holds the reboot. On Kubernetes nodes an `ExecCondition=` stands the local reboot down while kubelet or k0s runs, and `systemd-sysupdate.service` touches `/run/reboot-required` once an update is pending so Kured drains and reboots nodes one at a time. The lock files and the Kubernetes interlock come from [#182](https://github.com/projectbluefin/server/pull/182). Hosts without Kubernetes can share a reboot lock: with a FleetLock server configured, `bluefin-reboot-lock` takes a slot before the nightly reboot and the boot deadline's reboot and gives it back after a good boot, the protocol Zincati uses. Sources: [20-kured.conf](../../files/os/systemd/system/systemd-sysupdate.service.d/20-kured.conf), [20-interlock.conf](../../files/os/systemd/system/systemd-sysupdate-reboot.service.d/20-interlock.conf), [bluefin-reboot-lock](../../files/os/update-check/usr/libexec/bluefin-reboot-lock), [Kured project](https://github.com/kubereboot/kured), [FleetLock protocol](https://coreos.github.io/zincati/development/fleetlock/protocol/). |

## 4. Factual Gaps

### Root filesystem and A/B rollback

- **Resolved:** installs carry usr slots A and B (`files/os/repart.d/`);
  `systemd-sysupdate` fills the inactive slot and boot counting on the UKI
  rolls back a failed update (`just dogfood-install`).
- **Resolved:** `/usr` is a read-only erofs filesystem verified by dm-verity;
  the read-only state model is enforced at runtime, not by convention.

### Provisioning

- **Remaining gap:** The credential consumers are wired through systemd-native
  facilities, but TPM2-sealed credential decryption still needs a hardware boot
  proof on a TPM2-equipped host.

### Update delivery

- **Resolved:** installed nodes update and reboot on their own (`80-bluefin-updates.preset`), a boot is blessed only when no unit failed and is rebooted back to the previous image when it is not blessed in time (`bluefin-boot-deadline.timer`), and diskless nodes get a signed update signal (`bluefin-diskless-update-check`).
- **Resolved:** the diskless pull of the OS DDI runs with `verify=signature`; the initrd ships gnupg and the image keyring, so the download is checked against the signed `SHA256SUMS` before the pinned `usrhash=` / dm-verity checks even begin.

### Customization

- **No major gap found relative to the design intent.** `systemd-sysext` with a read-only, verity-sealed `/usr` matches the guarantees of Flatcar or Fedora CoreOS. Third-party extensions built for another distribution need `merge --force` since the host identifies as `ID=bluefin-server`.

### Reboot coordination

- **Resolved:** single-node and non-Kubernetes hosts reboot in the nightly `systemd-sysupdate-reboot.timer` window, held by `/run/reboot-lock` or `/etc/reboot-lock`; Kubernetes nodes stand down for Kured (lock files and interlock from #182).
- **Resolved:** non-Kubernetes hosts that serve together take turns through a FleetLock server, as with Zincati: `bluefin-reboot-lock` (bash and curl, no daemon) takes a slot before every local reboot and `bluefin-reboot-lock-release.service` returns it after a good boot. Bluefin Server ships the client only; the lock manager is any FleetLock server, where Flatcar's `locksmithd` builds it in on etcd. See [ddi-installer.md](ddi-installer.md) "Updates".

## 5. Summary of Biggest Gaps

1. **Credential provisioning hardware proof is incomplete.** SSH keys, Ignition configs, network files, and firstboot settings are wired through systemd credentials; TPM2-sealed decryption still needs a hardware boot proof.

The earlier gap on the unverified diskless DDI download is closed: the pull
runs with `verify=signature` against the keyring in the initrd. So is the
missing cluster-wide reboot lock outside Kubernetes: a FleetLock client gates
every local reboot.

These gaps drive the priorities in [architecture-roadmap.md](architecture-roadmap.md).

## 6. Sources Consulted

### Upstream distribution documentation

Specific claims carry inline links in section 2. Documentation roots:

- Ubuntu Server / autoinstall / cloud-init
  - <https://documentation.ubuntu.com/server/>
  - <https://canonical-subiquity.readthedocs-hosted.com/en/latest/intro-to-autoinstall.html>
  - <https://cloudinit.readthedocs.io/>
- Talos Linux — <https://docs.siderolabs.com/talos/v1.13/>
- Flatcar Container Linux — <https://www.flatcar.org/docs/latest/>
- Fedora CoreOS / rpm-ostree / Zincati
  - <https://docs.fedoraproject.org/en-US/fedora-coreos/>
  - <https://coreos.github.io/rpm-ostree/>
  - <https://coreos.github.io/zincati/>

### systemd reference

- <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysext.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysinstall.html>

### Bluefin Server source files

- [../../AGENTS.md](../../AGENTS.md)
- [../../CONTEXT.md](../../CONTEXT.md)
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)
- [systemd-sysext-extensions.md](systemd-sysext-extensions.md)
- [k0s-sysext.md](k0s-sysext.md)
- [factory-integration.md](factory-integration.md)
- [tpm2-credential-sealing.md](tpm2-credential-sealing.md)
- [elements/oci/bluefin-server-usr.bst](../../elements/oci/bluefin-server-usr.bst)
- [elements/oci/bluefin-server-boot.bst](../../elements/oci/bluefin-server-boot.bst)
- [elements/oci/bluefin-server-image.bst](../../elements/oci/bluefin-server-image.bst)
- [elements/bluefin-server/os-release.bst](../../elements/bluefin-server/os-release.bst)
- [elements/bluefin-server/os-creds-prov.bst](../../elements/bluefin-server/os-creds-prov.bst)
- [elements/bluefin-server/initrd/initrd-ignition.bst](../../elements/bluefin-server/initrd/initrd-ignition.bst)
- [files/os/repart.d/50-root.conf](../../files/os/repart.d/50-root.conf)
- [files/os/sysupdate.d/10-usr.transfer](../../files/os/sysupdate.d/10-usr.transfer)
- [files/os/sysupdate.d/20-uki.transfer](../../files/os/sysupdate.d/20-uki.transfer)
- [files/os/sysupdate.k0s.d/70-k0s.transfer](../../files/os/sysupdate.k0s.d/70-k0s.transfer)
- [files/os/sysusers.d/10-root-creds.conf](../../files/os/sysusers.d/10-root-creds.conf)
- [files/os/systemd/system-preset/80-bluefin-updates.preset](../../files/os/systemd/system-preset/80-bluefin-updates.preset)
- [files/os/systemd/system/systemd-sysupdate.service.d/20-kured.conf](../../files/os/systemd/system/systemd-sysupdate.service.d/20-kured.conf)
- [files/os/systemd/system/systemd-sysupdate-reboot.service.d/20-interlock.conf](../../files/os/systemd/system/systemd-sysupdate-reboot.service.d/20-interlock.conf)
- [files/os/systemd/system/bluefin-boot-deadline.timer](../../files/os/systemd/system/bluefin-boot-deadline.timer)
- [files/os/systemd/system/bluefin-reboot-lock-release.service](../../files/os/systemd/system/bluefin-reboot-lock-release.service)
- [files/os/update-check/usr/libexec/bluefin-reboot-lock](../../files/os/update-check/usr/libexec/bluefin-reboot-lock)
- [files/os/update-check/usr/libexec/bluefin-boot-deadline](../../files/os/update-check/usr/libexec/bluefin-boot-deadline)
- [files/os/update-check/usr/libexec/bluefin-diskless-update-check](../../files/os/update-check/usr/libexec/bluefin-diskless-update-check)
- [files/os/systemd/system/systemd-sysupdate.service.d/10-diskless.conf](../../files/os/systemd/system/systemd-sysupdate.service.d/10-diskless.conf)
