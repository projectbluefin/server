---
name: gap-analysis-architecture
description: "Use when reviewing or planning the implementation of Bluefin Server's core OS features, including updates, first-boot provisioning, security, and extensibility."
metadata:
  type: design-roadmap
  context7-sources:
    - /systemd/systemd
---

# Gap Analysis & Architectural Roadmap

This document outlines the gap analysis comparing Bluefin Server to Ubuntu Server, Talos Linux, Flatcar Container Linux, and Fedora CoreOS. It defines our systemd-native architectural decisions to address these gaps.

## When to Use

- Planning or implementing next-generation systemd-native features for Bluefin Server.
- Reviewing or updating the OS update mechanics, secure credential provisioning, and extension models.
- Desired alignment with the standard comparative architectures of other minimal server systems.

## When NOT to Use

- Single-package software builds that do not impact OS-level architecture.
- Simple, standalone CLI element bugs with no systemd architectural implications.

## Core Process

1. **OS Update Delivery & Rollbacks (systemd-sysupdate):** Configure target slots (`root-a`/`root-b`) and ESP slots. Match patterns against public GitHub Releases.
2. **First-Boot Provisioning Engine (systemd-creds):** Pass configuration drop-ins via ESP or hypervisor metadata (QEMU `fw_cfg`). Use `passwd.hashed-password.root` and `tmpfiles.extra`.
3. **Securing Provisioning Credentials (TPM2 Sealing):** Seal credentials against the node's TPM2 chip using `systemd-creds encrypt --seal`.
4. **Host-Level Customizations & Extensibility (systemd-sysext):** Build extensions matching Flatcar's major version metadata and load them dynamically.
5. **Reboot Coordination (Kured):** Write `/run/reboot-required` on update and coordinate rolling updates via Kured.

## Architectural Comparison Matrix

| Axis | Bluefin Server | Ubuntu Server | Talos Linux | Flatcar Linux | Fedora CoreOS |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Philosophy** | Image-based, minimal OS appliance. | Mutable general-purpose server. | API-managed Kubernetes appliance. | Minimal declarative container host. | Minimal declarative container host. |
| **State** | Ephemeral root with persistent `/var`. | Fully mutable. | Read-only SquashFS root with ephemeral tmpfs. | Read-only `/usr`, stateful ROOT partition. | Read-only `/usr`, mutable `/etc` and `/var`. |
| **Updates** | systemd-sysupdate (Planned). | APT packages. | API-driven A/B image. | Dual-slot partition cgpt switching. | Transactional rpm-ostree & Zincati. |
| **Provisioning** | systemd-creds (Planned). | cloud-init. | Single YAML config via gRPC API. | Ignition/Butane. | Ignition/Butane. |
| **Customization** | systemd-sysext / Flatcar bakery. | APT packages. | Containerized only. | systemd-sysext / Bakery. | rpm-ostree package layering. |
| **Reboots** | Kured via `/run/reboot-required`. | Traditional. | Custom controller. | locksmithd (etcd-lock). | Zincati. |

## Standardized Solutions & Design Decisions

### 1. OS Update Delivery & Rollbacks (A/B via systemd-sysupdate)
To maintain our systemd-native philosophy and avoid custom agents, Bluefin Server utilizes **`systemd-sysupdate`** for atomic over-the-air (OTA) updates:
- **Delivery Vehicle:** Public GitHub Releases.
- **Signature Verification:** SHA256SUMS manifests are signed in CI with a project GPG key. The public keyring ships in `/usr/lib/systemd/import-pubring.pgp` and `systemd-sysupdate` verifies detached `SHA256SUMS.gpg` signatures by default (`Verify=yes`).
- **Client Configuration:** Dual-slot configuration (`root-a`/`root-b` on target disk) and matching ESP UKI slots (`uki-a`/`uki-b`).
- **Mechanism:** `systemd-sysupdate` running on the client pulls the latest target UKI (`bluefin-server-@v.efi`) and compressed DDI (`bluefin-server-ddi-@v.raw.xz`) from GitHub Releases, verifies the manifest signatures and file hashes, flashes them block-for-block to the inactive slots, and marks `/run/reboot-required`.

### 2. First-Boot Provisioning Engine (systemd-creds)
Declarative system setups (users, network links, SSH keys) are handled natively using **systemd credentials**:
- **Delivery Channel:** Passed securely to the VM/host via ESP directory structure, container manager `--set-credential`, or hypervisor metadata (QEMU `fw_cfg` via `-smbios type=11`).
- **Implementation:**
  - `passwd.hashed-password.root` is read automatically by `systemd-sysusers` to configure root password.
  - `tmpfiles.extra` is read automatically by `systemd-tmpfiles` to write files like `/root/.ssh/authorized_keys` securely.

### 3. Securing Provisioning Credentials (TPM2 Sealing)
Sensitive configuration credentials (such as hashes and key data) must be cryptographically protected:
- **Solution:** Encrypt and seal credentials using **`systemd-creds encrypt --seal`**.
- **Constraint:** Sealed against the system's **TPM2** chip (PCR 7/11, verifying the boot loader and firmware state) to prevent unauthorized decryption outside our authentic Unified Kernel Image.

### 4. Host-Level Customizations & Extensibility (Flatcar Sysext Compatibility)
Instead of package layering or custom compilation, Bluefin Server supports dynamic package extensions using systemd's native extension mechanisms:
- **Mechanism:** **`systemd-sysext`** and **`systemd-confext`** merge raw extension images directly into `/usr` or `/etc` via overlayfs.
- **Flatcar Compatibility:** By mimicking Flatcar's `/usr/lib/os-release` metadata (`ID=flatcar`, matching `VERSION_ID` major lines), Bluefin Server can run any pre-compiled system extensions distributed by the **Flatcar System Extension Bakery**.

### 5. Reboot Coordination (Kured Integration)
Rolling updates across Kubernetes nodes must not impact cluster availability:
- **Solution:** Standardize on **Kured (Kubernetes Reboot Daemon)**.
- **Trigger:** When `systemd-sysupdate` stages an update, a post-install hook creates `/run/reboot-required`. Kured drains the node, reboots the host, and uncordons it once healthy.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Let's write a python or go daemon to pull and apply updates." | Avoid custom daemons. `systemd-sysupdate` handles transactional block-level or file-level upgrades natively. |
| "Use cloud-init or Ignition for VM provisioning." | This drags in heavy packages and external configuration parsers. `systemd-creds` is ultra-lightweight and integrated directly into Pid 1. |

## Red Flags

- Suggesting an in-place daemon or package manager to download updates instead of `systemd-sysupdate`.
- Proposing custom boot scripts or agents to parse SSH authorized keys on first boot instead of utilizing `tmpfiles.extra` credentials.
- Packaging tools in the base OS image instead of shipping them as independent `systemd-sysext` extensions.

## Verification

- [ ] `systemd-sysupdate` transfer files do not disable verification (`Verify=no`).
- [ ] The OS image ships the public keyring at `/usr/lib/systemd/import-pubring.pgp`.
- [ ] CI signs `SHA256SUMS` manifests and uploads matching `.gpg` detached signatures.
- [ ] New system configurations align with `systemd-creds` specs.
- [ ] Extension images verify compatibility against `ID=flatcar` and match target Flatcar board architecture.
- [ ] Update staging writes cleanly to `/run/reboot-required` to trigger Kured.

