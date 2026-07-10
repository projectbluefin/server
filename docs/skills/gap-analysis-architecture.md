---
name: gap-analysis-architecture
description: "Roadmap and architectural design for Bluefin Server features, detailing systemd-sysupdate, systemd-creds, and Flatcar sysext compatibility."
metadata:
  type: design-roadmap
---

# Gap Analysis & Architectural Roadmap

This document outlines the gap analysis comparing Bluefin Server to Ubuntu Server, Talos Linux, Flatcar Container Linux, and Fedora CoreOS. It defines our systemd-native architectural decisions to address these gaps.

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
- **Client Configuration:** Dual-slot configuration (`root-a`/`root-b` on target disk) and matching ESP UKI slots (`uki-a`/`uki-b`).
- **Mechanism:** `systemd-sysupdate` running on the client pulls the latest target UKI (`bluefin-server-@v.efi`) and compressed DDI (`bluefin-server-ddi-@v.raw.xz`) from GitHub Releases, flashes them block-for-block to the inactive slots, and marks `/run/reboot-required`.

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
