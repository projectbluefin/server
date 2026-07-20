# Bluefin Server MVP 1.0 Readiness Audit & Plan

> Status: work in progress — generated while verifying the current build/test
> baseline on the lab cluster.

## 1. What MVP 1.0 means here

A first public/usable release is more than "it compiles." The minimum bar for
MVP 1.0 is:

1. **Reproducible build path** — a documented command or CI job that produces
   the OS DDI, live installer, and `k3s` sysext from source.
2. **Signed release artifacts** — combined `SHA256SUMS` + detached GPG signature
   published to GitHub Releases for `systemd-sysupdate` verification.
3. **Automated boot verification** — at least one non-human test that proves the
   installer writes a bootable disk and the installed OS reaches a login-ready
   state.
4. **Functional update path** — a host can pull the signed manifest and apply an
   OS update without manual intervention.
5. **Basic first-boot provisioning** — an unattended way to set the root
   credential and drop an SSH authorized key, because there is no shell in the
   running DDI image.
6. **Documented recovery** — either A/B rollback or a reinstall-from-media path
   when an update fails to boot.

## 2. Verified current state

| Check | Status | Evidence |
|---|---|---|
| Element graph resolves | ✅ Pass | `just validate` succeeds for DDI, installer, and k3s sysext |
| GitHub Actions workflow lint | ✅ Pass | `actionlint .github/workflows/build.yml` clean after fixes |
| GitHub Actions release path | ✅ Exists | `.github/workflows/build.yml` builds DDI/installer/sysext, signs `SHA256SUMS`, uploads to GitHub Release |
| Cluster build pipeline | 🔧 Fixed | Template had 90m pod deadline that killed cold-cache builds; deadline extended in `projectbluefin/lab` and ArgoCD synced; a new run is in progress |
| Automated boot test | ❌ Missing | There is no Argo workflow that boots a Bluefin Server VM; only local `just show-me-the-future` QEMU smoke test |
| Unit tests | ❌ Missing | There are no unit tests in this repository (`.pytest_cache` is stale) |
| A/B root rollback | ❌ Not wired | `50-root.transfer` names `root-a`/`root-b`, but installer only creates `root-a` |
| Root immutability | ❌ Not enforced | DDI boots read/write (`rw` on cmdline) |
| First-boot SSH keys | ❌ Not implemented | Only `root` password credential path exists |

## 3. Competitor audit (summary)

Source-verified comparison lives in [docs/skills/gap-analysis-distros.md](docs/skills/gap-analysis-distros.md).
Competitors scored against the MVP bar above:

| OS | A/B rollback | Immutable /usr | Signed OTA | First-boot creds | Coordinated reboot |
|---|---|---|---|---|---|
| Ubuntu Server | ❌ apt is in-place | ❌ fully mutable | ✅ unattended-upgrades + Pro | ✅ cloud-init/autoinstall | ❌ external |
| Talos Linux | ✅ API-driven A/B | ✅ read-only SquashFS | ✅ `talosctl upgrade` | ✅ machine config YAML | ✅ drains nodes |
| Flatcar Container Linux | ✅ dual root + update-engine | ✅ read-only `/usr` | ✅ `update-engine` | ✅ Ignition/Butane | ✅ locksmithd |
| Fedora CoreOS | ✅ rpm-ostree deployments | ✅ OSTree immutable `/usr` | ✅ Zincati + Cincinnati | ✅ Ignition/Butane | ✅ FleetLock |
| Bluefin Server (current) | ❌ single root slot | ❌ boots `rw` | ✅ `systemd-sysupdate` + GPG | ⚠️ root password only | ⚠️ Kured hook only |

## 4. MVP 1.0 verdict

**NOT READY** as of today. The build/release plumbing exists and is now being
fixed, but the runtime still lacks:

- An automated proof that the installed OS boots.
- A safe update/rollback story.
- Complete first-boot credential delivery.

These are not cosmetic gaps. A server OS shipped without automated boot
verification and recovery is not a viable 1.0 product.

## 5. Roadmap to MVP 1.0

Priority order. Each item depends on the ones above it.

### Phase A: prove the build path (in progress)

1. ✅ Extend Argo build deadlines so the cluster pipeline can finish.
2. ✅ Fix `build.yml` actionlint warnings.
3. ⏳ Wait for the current cluster build to succeed and publish to local Zot.
4. Add the `oci/k3s-sysext.bst` build to the cluster pipeline (it currently
   only builds DDI + installer).

### Phase B: automated boot verification

5. Create an Argo workflow that:
   - Pulls the installer OCI from Zot.
   - Creates a target raw disk.
   - Boots the installer in a KubeVirt VM with the target disk attached.
   - Waits for install completion and reboots into the installed OS.
   - Collects systemd journal and `systemctl --failed` output.
   - Tears down the VM.
6. Wire the boot-test workflow into `.github/workflows/build.yml` or run it as
   a post-merge Argo CronWorkflow.

### Phase C: update/rollback and provisioning

7. **A/B root partitions**: add `20-root-b.conf` to the installer repart recipes
   and ensure `systemd-sysupdate` stages into the inactive slot.
8. **Read-only `/usr`**: switch UKI cmdline from `rw` to `ro` and rely on
   `/var` for mutable state.
9. **First-boot credentials**: consume sealed/encrypted credentials via
   `systemd-creds` for SSH authorized keys and static network config.
10. **Recovery selection**: boot menu entry that selects the previous slot after
    a failed update.

### Phase D: release discipline

11. Tag a `v1.0.0-MVP` pre-release once Phase B passes.
12. Publish release notes: verified boot path, update trust model, known gaps.

## 6. Immediate next actions

- [ ] Confirm the new cluster build run completes and writes
      `bluefin-server-ddi:latest` and `bluefin-server-installer:latest` to
      `192.168.1.102:30500`.
- [ ] Create the boot-test workflow (Phase B, item 5).
- [ ] Decide whether MVP 1.0 requires A/B dual-slot rollback or whether a
      single-slot signed update with documented reinstall recovery is
      acceptable for the first release.

## Files touched so far

- `projectbluefin/lab`:
  - `argo/workflow-templates/bluefin-server-build-pipeline.yaml`
- `projectbluefin/server`:
  - `.github/workflows/build.yml`
  - `docs/MVP_1_0_READINESS.md` (this file)
