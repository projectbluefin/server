---
name: architecture-roadmap
description: Roadmap for future Bluefin Server architecture work. Use when planning long-lead systemd-native capabilities.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-08"
  context7-sources:
    - /systemd/systemd
---

# Architecture Roadmap

Status: current roadmap.

This file captures planned architecture work and the rationale behind it. Verified implementation rules now live in [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md), [tpm2-credential-sealing.md](tpm2-credential-sealing.md), and [systemd-sysext-extensions.md](systemd-sysext-extensions.md).
The source-verified gap analysis lives in [gap-analysis-distros.md](gap-analysis-distros.md).

## Done

For reference, so future planning does not redo them:

- A/B usr slots with `systemd-sysupdate` and boot-counted automatic rollback (`files/os/repart.d/`, `files/os/sysupdate.d/`).
- Read-only erofs `/usr` verified by dm-verity, pinned by `usrhash=` in the signed UKIs.
- Diskless network boot (`rd.systemd.pull` of the OS DDI into RAM, `verify=signature` against the initrd keyring) and diskless-native install via `systemd-sysinstall`.
- Secure Boot end to end (signed systemd-boot, signed UKIs, signed modules, `lockdown=integrity`).
- Opt-in Ignition provisioning via system credentials, plus `bluefin-node.ign` next to the UKI on UEFI HTTP boot.
- k0s role units (controller vs worker); KubeStellar is a homelab add-on sysext applied by the homelab applier on kubeadm or k0s.
- Combined `SHA256SUMS` over the whole image set, signed inside `oci/bluefin-server-image.bst` and verified by both sysupdate and the diskless pull.
- OCI artifact output (`ghcr.io/<owner>/bluefin-server:<ver>,latest`) alongside the raw release files, via ORAS in CI and `just publish-oci` locally.
- Booty HTTP boot: per-MAC serving of the UKI, DDI, `SHA256SUMS(.gpg)`, and per-host `bluefin-node.ign`, verified end to end in QEMU with Secure Boot; merged upstream in [jeefy/booty#39](https://github.com/jeefy/booty/pull/39).
- ZFS and KubeStellar sysexts version-locked to the image, delivered in lock-step with OS updates through sysupdate features; rollback keeps the matching sysext.
- Automatic updates on installed nodes (preset-enabled `systemd-sysupdate.timer` and `systemd-sysupdate-reboot.timer`), operator reboot lock files and a kured interlock for Kubernetes nodes (from #182), a boot health gate (`systemd-boot-check-no-failures.service`) whose deadline reboots an unhealthy counted boot back to the previous image (`bluefin-boot-deadline.timer`), and a signed update signal for diskless nodes that are not pinned to a versioned image (`bluefin-diskless-update-check`); see [ddi-installer.md](ddi-installer.md) "Updates".
- Cluster-wide reboot lock for non-Kubernetes fleets: a FleetLock client (`bluefin-reboot-lock`, bash and curl, no daemon) takes a slot from a configured FleetLock server before the nightly and boot-deadline reboots and releases it after a good boot; see [ddi-installer.md](ddi-installer.md) "Updates".

## Planned work

Priorities are derived from [gap-analysis-distros.md](gap-analysis-distros.md).

| # | Item | Rationale / source gap |
|---|------|------------------------|
| 1 | TPM2-sealed /var on installed nodes | Credential sealing exists (`tpm2-credential-sealing.md`); persistent state is not yet bound to the TPM. |
| 2 | aarch64 build axis | `project.conf`, `include/arch.yml` and the k0s/kubeadm arm64 binary pins resolve `-o arch aarch64`. Missing: aarch64 FSDK artifacts in any cache (a full bootstrap build), an aarch64 CI build, and an aarch64 dogfood path (`scripts/dogfood-*.sh` run `qemu-system-x86_64` with x64 OVMF). |
| 3 | Booty Secure Boot shim story | Bluefin HTTP-boot support is merged in [Booty](https://github.com/jeefy/booty) ([jeefy/booty#39](https://github.com/jeefy/booty/pull/39)). Shim built from source with the DB certificate as vendor certificate, laid out on the netboot and installer ESPs, landed behind `-o shim True` (unsigned by Microsoft). Missing: the shim-review submission and Microsoft signature, the installed-disk shim layout, and a shim chain over HTTP boot ("Shim path" in [ddi-installer.md](ddi-installer.md)). |
| 4 | Credential provisioning smoke tests on real hardware | SSH keys, static network, and firstboot settings are wired through systemd credentials; TPM2-sealed credential decryption still needs hardware proof. |

## Status notes

- The current tree intentionally favors a small, verifiable core: verity-sealed `/usr`, A/B slots, signed boot chain, opt-in sysexts.
- Any implementation work should preserve the current systemd-native model and avoid custom daemons.
- See [gap-analysis-distros.md](gap-analysis-distros.md) for the source-verified comparison that produced this list.

## Decided, not planned

- **OS payload and kernel source.** Between #132 and #262 the OS payload was briefly the imported Flatcar `/usr` with its kernel, and [#249](https://github.com/projectbluefin/server/issues/249) collected notes on shipping alternative kernels (Fedora CoreOS, Flatcar LTS, Ubuntu Server) as extra UKIs. #262 settled this: the whole OS, kernel included, composes from FSDK components (AGENTS.md hard rule 1), and there is one kernel per image. Alternative kernels or a Flatcar-based payload are not planned; reopening either means changing hard rule 1 first.
- **Installer and per-node configuration.** The same notes left "pure systemd" against "also support Ignition / cloud-init" open. #262 kept stock `systemd-sysinstall` as the only installer (hard rule 3) and opt-in Ignition delivered as a system credential, next to systemd's own first-boot credentials; cloud-init is not planned. The boot and install flow is in [ddi-installer.md](ddi-installer.md), the credentials in [tpm2-credential-sealing.md](tpm2-credential-sealing.md).

## See also

- [gap-analysis-distros.md](gap-analysis-distros.md) — source-verified distro comparison.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
