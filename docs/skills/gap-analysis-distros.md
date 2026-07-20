---
name: gap-analysis-distros
description: |
  Source-verified gap analysis comparing Bluefin Server to Ubuntu Server, Talos Linux,
  Flatcar Container Linux, and Fedora CoreOS.
metadata:
  type: reference
  status: stable
  last_updated: 2026-07-20
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

Bluefin Server is a BuildStream 2-based, image-based Linux server OS built from FSDK components.

| Axis | Bluefin Server (as-implemented) |
|------|---------------------------------|
| **Philosophy** | Systemd-native, minimal, image-based server OS appliance; base DDI is distroless; intended to run container workloads and Kubernetes via optional sysexts. Sources: [AGENTS.md](../../AGENTS.md), [factory-integration.md](factory-integration.md). |
| **State model** | Target OS DDI is an XFS filesystem image. A separate persistent `/var` partition is created by the installer. There is no second root slot provisioned today, and the UKI cmdline currently uses `rw`, so the root is not mounted read-only at runtime. Sources: [bluefin-server-ddi.bst](../../elements/oci/bluefin-server-ddi.bst), [20-root-a.conf](../../files/installer/repart.d/20-root-a.conf), [bluefin-server-installer.bst](../../elements/oci/bluefin-server-installer.bst). |
| **Updates** | `systemd-sysupdate` reads `files/os/sysupdate.d/*.transfer`. Assets are published to GitHub Releases, and the combined `SHA256SUMS` manifest is signed in CI with a GPG key. `Verify=yes` is the default. Sources: [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md), [50-root.transfer](../../files/os/sysupdate.d/50-root.transfer), [60-uki.transfer](../../files/os/sysupdate.d/60-uki.transfer), [70-k3s.transfer](../../files/os/sysupdate.d/70-k3s.transfer), also `systemd-sysupdate(8)`. |
| **Provisioning** | The installer is an offline `systemd-sysinstall` image that embeds the DDI as a data partition. First-boot configuration is intended to be delivered via `systemd-creds` through the ESP or hypervisor metadata. Today only `passwd.hashed-password.root` is consumed via `systemd-sysusers.d`; the documented `tmpfiles.extra` path for SSH keys and similar files is not implemented. Sources: [bluefin-server-installer.bst](../../elements/oci/bluefin-server-installer.bst), [10-root-creds.conf](../../files/os/sysusers.d/10-root-creds.conf), [os-creds-prov.bst](../../elements/bluefin-server/os-creds-prov.bst), [systemd-creds(1)](https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html). |
| **Customization** | Adds software through `systemd-sysext` (overlay `/usr`) and `systemd-confext` (overlay `/etc`) images. The base OS `os-release` advertises `ID=flatcar` and a matching `VERSION_ID` so pre-built Flatcar Bakery extensions load. k3s is shipped as a separately built, optionally enabled sysext. Sources: [systemd-sysext-extensions.md](systemd-sysext-extensions.md), [k3s-sysext.md](k3s-sysext.md), [os-release-flatcar.bst](../../elements/bluefin-server/os-release-flatcar.bst), [systemd-sysext(8)](https://www.freedesktop.org/software/systemd/man/latest/systemd-sysext.html). |
| **Reboot coordination** | `systemd-sysupdate.service` has an `ExecStartPost` that touches `/run/reboot-required`. Rolling reboots across Kubernetes nodes rely on Kured reading that file. Sources: [os-kured-hook.bst](../../elements/bluefin-server/os-kured-hook.bst), [kured-hook.conf](../../files/os/systemd/systemd-sysupdate.service.d/kured-hook.conf), [Kured project](https://github.com/weaveworks/kured). |

## 4. Factual Gaps

### Root filesystem and A/B rollback

- **Gap:** Bluefin's `systemd-sysupdate` root transfer already names two target partitions (`root-a` and `root-b`) in `50-root.transfer`, but the installer only creates one root partition (`20-root-a.conf`).
  There is no `root-b` partition yet, so `systemd-sysupdate` cannot stage an update into an inactive slot and the OS has no atomic rollback path comparable to Flatcar/Fedora CoreOS/Talos today.
- **Gap:** The DDI filesystem is created as a writable XFS image and the installed UKI boots it with `rw`. A read-only `/usr` state model, as intended by the sysext-first design, is not enforced at runtime.
- **Gap:** There is no mechanism to select the previous OS version at boot if an update fails; recovery currently depends on reinstalling from media.

### Provisioning

- **Gap:** The documented `systemd-creds` first-boot provisioning for SSH keys (`tmpfiles.extra`) is not present in the build (`os-creds-prov.bst` only ships `sysusers.d`).
  Operators can only pre-seed the root password today.
- **Gap:** `systemd-firstboot` is masked in the installer environment, so interactive first-boot questions are skipped; any further user/network/timezone configuration must be supplied through credentials that the build does not yet consume.
- **Gap:** TPM2 sealing for credentials is documented in `docs/skills/tpm2-credential-sealing.md`, but there is no evidence in the OS build that sealed credentials are generated, shipped, or decrypted automatically during first boot.

### Update delivery

- **Gap:** The root transfer uses `Type=partition Path=auto`, which requires `systemd-sysupdate` to discover a matching GPT partition label (`bluefin-server-root-a`/`root-b`). This is correct, but without a `root-b` partition the transfer effectively overwrites the running root in place.
- **Gap:** `systemd-sysupdate-reboot.service`/`systemd-sysupdate-reboot.timer` are not enabled or configured; the only reboot signal today is the Kured hook.

### Customization

- **No major gap found relative to the design intent.** `systemd-sysext` and Flatcar Bakery compatibility match the intended extension model. The main operational concern is that, because `/usr` is not mounted read-only, a sysext merge vs. runtime writes to `/usr` have different guarantees than on Flatcar or Fedora CoreOS.

### Reboot coordination

- **Gap:** Kured coordinates Kubernetes node reboots but requires Kubernetes to be running. There is no equivalent for single-node or non-Kubernetes Bluefin hosts, and there is no built-in cluster lock manager similar to Zincati's FleetLock or Flatcar's `locksmithd`/`etcd-lock`.

## 5. Summary of Biggest Gaps

1. **A/B dual-slot rollback is not wired end-to-end.** The `sysupdate` transfer names `root-a`/`root-b`, but the installer only provisions `root-a`, so Bluefin cannot atomically stage and roll back a new root image today.
2. **Root filesystem immutability is not enforced.** The DDI is built and booted read-write; the intended read-only `/usr` + overlay model depends entirely on optional sysext behavior rather than runtime policy.
3. **First-boot credential provisioning is incomplete.** Only the `root` password credential path is shipped; SSH keys, network configuration, and other `systemd-creds`-based provisioning remain documented but not implemented.

These gaps drive the priorities in [architecture-roadmap.md](architecture-roadmap.md).

## 6. Sources Consulted

### Upstream distribution documentation

- Ubuntu Server / autoinstall / cloud-init
  - <https://documentation.ubuntu.com/server/>
  - <https://raw.githubusercontent.com/canonical/ubuntu-server-documentation/main/docs/how-to/software/automatic-updates.md>
  - <https://raw.githubusercontent.com/canonical/ubuntu-server-documentation/main/docs/how-to/software/upgrade-your-release.md>
  - <https://raw.githubusercontent.com/canonical/ubuntu-server-documentation/main/docs/how-to/software/package-management.md>
  - <https://canonical-subiquity.readthedocs-hosted.com/en/latest/intro-to-autoinstall.html>
  - <https://cloudinit.readthedocs.io/>
- Talos Linux
  - <https://docs.siderolabs.com/talos/v1.13/overview/what-is-talos.md>
  - <https://docs.siderolabs.com/talos/v1.13/configure-your-talos-cluster/lifecycle-management/upgrading-talos.md>
  - <https://docs.siderolabs.com/talos/v1.13/build-and-extend-talos/custom-images-and-development/system-extensions.md>
  - <https://docs.siderolabs.com/talos/v1.13/reference/configuration/overview.md>
- Flatcar Container Linux
  - <https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/setup/releases/update-strategies.md>
  - <https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/provisioning/ignition/_index.md>
  - <https://raw.githubusercontent.com/flatcar/flatcar-docs/main/docs/provisioning/sysext/_index.md>
- Fedora CoreOS / rpm-ostree / Zincati
  - <https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/index.adoc>
  - <https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/auto-updates.adoc>
  - <https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/producing-ign.adoc>
  - <https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/running-containers.adoc>
  - <https://raw.githubusercontent.com/coreos/fedora-coreos-docs/main/modules/ROOT/pages/faq.adoc>
  - <https://raw.githubusercontent.com/coreos/rpm-ostree/main/README.md>
  - <https://coreos.github.io/zincati/>
  - <https://coreos.github.io/zincati/development/fleetlock/>

### systemd reference

- <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysupdate.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysext.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html>
- <https://www.freedesktop.org/software/systemd/man/latest/systemd-sysinstall.html>

### Bluefin Server source files

- [../../AGENTS.md](../../AGENTS.md)
- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)
- [systemd-sysext-extensions.md](systemd-sysext-extensions.md)
- [k3s-sysext.md](k3s-sysext.md)
- [factory-integration.md](factory-integration.md)
- [tpm2-credential-sealing.md](tpm2-credential-sealing.md)
- [elements/oci/bluefin-server-ddi.bst](../../elements/oci/bluefin-server-ddi.bst)
- [elements/oci/bluefin-server-installer.bst](../../elements/oci/bluefin-server-installer.bst)
- [elements/bluefin-server/os-release-flatcar.bst](../../elements/bluefin-server/os-release-flatcar.bst)
- [elements/bluefin-server/os-creds-prov.bst](../../elements/bluefin-server/os-creds-prov.bst)
- [elements/bluefin-server/os-kured-hook.bst](../../elements/bluefin-server/os-kured-hook.bst)
- [files/installer/repart.d/20-root-a.conf](../../files/installer/repart.d/20-root-a.conf)
- [files/os/sysupdate.d/50-root.transfer](../../files/os/sysupdate.d/50-root.transfer)
- [files/os/sysupdate.d/60-uki.transfer](../../files/os/sysupdate.d/60-uki.transfer)
- [files/os/sysupdate.d/70-k3s.transfer](../../files/os/sysupdate.d/70-k3s.transfer)
- [files/os/sysusers.d/10-root-creds.conf](../../files/os/sysusers.d/10-root-creds.conf)
- [files/os/systemd/systemd-sysupdate.service.d/kured-hook.conf](../../files/os/systemd/systemd-sysupdate.service.d/kured-hook.conf)
