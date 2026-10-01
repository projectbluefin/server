# Bluefin Server MVP 1.0 Readiness Audit

This audit tracks the gap between the current tree and a first public/usable MVP 1.0 release.

## MVP 1.0 bar

1. **Reproducible build path** — documented command or CI job that produces the OS DDI, signed UKIs, netboot ESP, and sysexts.
2. **Signed release artifacts** — combined `SHA256SUMS` + detached GPG signature covering the whole image set, published to GitHub Releases and as an OCI artifact.
3. **Automated boot verification** — at least one non-human test that proves the image boots and installs.
4. **Functional update path** — host can pull the signed manifest and apply an OS update without manual intervention.
5. **Basic first-boot provisioning** — unattended way to set root credential and drop an SSH authorized key.
6. **Documented recovery** — A/B rollback or reinstall path for a failed update.

## Current state

| Check | Status | Evidence |
|---|---|---|
| Element graph resolves | ✅ | `just validate` succeeds for the image set and all three sysexts |
| Release workflow lint | ✅ | `actionlint .github/workflows/build.yml` clean |
| Release path exists | ✅ | `.github/workflows/build.yml` signs `SHA256SUMS` in-element (`oci/bluefin-server-image.bst`, with a `gpgv` proof against the shipped keyring) and publishes immutable `v<image-version>` GitHub Releases plus the OCI artifact `ghcr.io/<owner>/bluefin-server:<ver>,latest` |
| Automated boot test | ✅ | `boot-test` job in `build.yml` runs `scripts/dogfood-diskless.sh --check` and `scripts/dogfood-install.sh` on every PR and push to main; locally `just dogfood-check` / `just dogfood-install`. UEFI HTTP boot verified with Secure Boot (`DOGFOOD_BOOT=http`), and tampered DDI / unsigned manifest both refused (`DOGFOOD_TAMPER=raw\|sums`) |
| A/B rollback | ✅ | `files/os/repart.d/` provisions usr slots A+B; `systemd-sysupdate` fills the inactive slot and UKI boot counting (`TriesLeft=3` in `files/os/sysupdate.d/20-uki.transfer`) rolls back failed boots, and `bluefin-boot-deadline.timer` reboots a counted boot that misses `boot-complete.target`; proven by `scripts/dogfood-install.sh <dir> <next> <broken>` (`DOGFOOD_BROKEN=slot` or `unit`) |
| Read-only /usr | ✅ | erofs + dm-verity pinned by `usrhash=` in the signed UKIs (`elements/oci/bluefin-server-usr.bst`, `elements/oci/bluefin-server-boot.bst`) |
| Signed diskless pull | ✅ | Netboot UKI pulls with `verify=signature`; the initrd ships gnupg and the keyring (`/etc/systemd/import-pubring.pgp` from `os-sysupdate-keys.bst`) |
| Automatic updates | ✅ | Installed nodes: `80-bluefin-updates.preset` enables `systemd-sysupdate.timer` and `systemd-sysupdate-reboot.timer`; Kubernetes nodes set `/run/reboot-required` and leave the reboot to kured (`ExecCondition=` interlock); `systemd-boot-check-no-failures.service` gates `boot-complete.target`, so only a boot with no failed unit is blessed, and `bluefin-boot-deadline.timer` reboots (or flags kured for) a counted boot that is not blessed in 15 minutes; `/run/reboot-lock` and `/etc/reboot-lock` hold local reboots. Diskless nodes: `bluefin-diskless-update-check` flags a newer signed release on the boot server unless the node is pinned to a versioned image. See [ddi-installer.md](skills/ddi-installer.md) "Updates" |
| Sysext lock-step updates | ✅ | `zfs` / `kubestellar` sysupdate features download the version-locked sysext with each OS update; rollback keeps the matching sysext (verified in the 6-phase `dogfood-install` run) |
| First-boot SSH keys | ✅ | Ignition (`ignition.config` / `ignition.config.url` credentials, or `bluefin-node.ign` next to the UKI on UEFI HTTP boot; `tests/fixtures/ignition/var-on-disk.ign`) and `tmpfiles.extra` / sysusers credentials (`elements/bluefin-server/os-creds-prov.bst`) |

Competitor context: [gap-analysis-distros.md](skills/gap-analysis-distros.md)

## Verdict

**Alpha state — on track for MVP 1.0.** The build path, signed releases (GitHub + OCI), automated boot verification (including UEFI HTTP boot and Booty-provisioned install), A/B rollback, read-only /usr, lock-step sysext updates, and unattended provisioning are all implemented and exercised in CI. Installed nodes update and reboot on their own, with a Kubernetes interlock and a boot health gate. Remaining work is hardening: TPM2-sealed state, a cluster-wide reboot lock for non-Kubernetes fleets, and real-hardware boot proofs.

## Roadmap

Priority order. Each item depends on the ones above it.

### Phase A: build path and core artifacts (Complete)

- [x] Merge-contract graph validation (`just validate`) passes clean.
- [x] Add the k0s and OpenZFS sysexts to the build and validation pipeline.
- [x] Release workflow builds, signs, and publishes immutable GitHub Releases.

### Phase B: automated boot verification (Complete)

- [x] Secure Boot QEMU diskless boot check (`scripts/dogfood-diskless.sh --check`).
- [x] Diskless -> install -> disk boot check (`scripts/dogfood-install.sh`).
- [x] Boot test wired into `build.yml` as the `boot-test` job gating releases.
- [x] UEFI HTTP boot with Secure Boot and per-node `bluefin-node.ign` (`DOGFOOD_BOOT=http`), plus negative signature checks (`DOGFOOD_TAMPER`).
- [x] Booty end-to-end run: synced from a local OCI registry with the keyring, HTTP-booted a node with Secure Boot, applied hostname/SSH key, merged ZFS, installed to disk via doInstall.

### Phase C: update/rollback and provisioning (Complete)

- [x] usr slot B created on first disk boot; `systemd-sysupdate` stages into the inactive slot.
- [x] /usr is read-only erofs under dm-verity; the persistent root is xfs.
- [x] Boot-counted UKIs roll back a failed update automatically.
- [x] ZFS/KubeStellar sysexts follow OS updates in lock-step via sysupdate features and survive rollback.
- [x] SSH authorized keys via Ignition and `systemd-creds` (`tmpfiles.extra`).

### Phase D: release discipline

- [ ] TPM2-sealed /var and credential decryption proof on real hardware.
- [x] Reboot coordination for non-Kubernetes hosts: nightly `systemd-sysupdate-reboot.timer`, operator lock files and a kured interlock (both from #182), and a boot health gate that reboots an unhealthy counted boot (#139).
- [ ] Cluster-wide reboot lock (FleetLock-style) for multi-node fleets without Kubernetes.
- [x] Booty Bluefin support merged upstream ([jeefy/booty#39](https://github.com/jeefy/booty/pull/39)): UEFI HTTP boot, iPXE chainload, legacy BIOS diskless, per-node Ignition, kubeadm join, install-to-disk.
- [ ] Shim-signed Secure Boot path for enrollment-free first boots.
- [ ] Tag `v1.0.0-MVP` once Phase D items land.
- [ ] Publish release notes: verified boot path, trust model, known gaps.

## Related files

- Downstream factory CI repository Argo workflow templates
- `projectbluefin/server/.github/workflows/build.yml`
- `docs/skills/gap-analysis-distros.md`
- `docs/skills/architecture-roadmap.md`
