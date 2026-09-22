# Bluefin Server MVP 1.0 Readiness Audit

This audit tracks the gap between the current tree and a first public/usable MVP 1.0 release.

## MVP 1.0 bar

1. **Reproducible build path** — documented command or CI job that produces the DDI, live installer, and k0s sysext.
2. **Signed release artifacts** — combined `SHA256SUMS` + detached GPG signature published to GitHub Releases.
3. **Automated boot verification** — at least one non-human test that proves the installer writes a bootable disk and the installed OS reaches a target.
4. **Functional update path** — host can pull the signed manifest and apply an OS update without manual intervention.
5. **Basic first-boot provisioning** — unattended `core` operator key-provisioning model for SSH authorized keys.
6. **Documented recovery** — A/B rollback or reinstall-from-media path for a failed update.

## Current state

| Check | Status | Evidence |
|---|---|---|
| Element graph resolves | ✅ | `just validate` succeeds for DDI, installer, and k0s sysext |
| Release workflow lint | ✅ | `actionlint .github/workflows/build.yml` clean |
| Release path exists | ✅ | `.github/workflows/build.yml` builds, signs, uploads to GitHub Release |
| Cluster build pipeline | ✅ | Phase A complete; pipeline builds DDI, installer, and k0s sysext with uutils |
| Automated boot test | 🔄 | Phase B in progress for Alpha; `bluefin-server-boot-test` workflow running on lab cluster |
| A/B root rollback | ❌ | `50-root.transfer` names `root-a`/`root-b`, installer only creates `root-a` |
| Root immutability | ❌ | DDI boots read/write (`rw` on cmdline) |
| First-boot SSH keys | ✅ | Implemented `tmpfiles.extra` path writing `/var/home/core/.ssh/authorized_keys` |

Competitor context: [gap-analysis-distros.md](skills/gap-analysis-distros.md)

## Verdict

**Alpha state — in progress for MVP 1.0.** Phase A (build path, uutils, k0s sysext, validate) is complete. Phase B (automated boot test on lab cluster) is actively in progress for the Alpha milestone. Full MVP 1.0 release requires concluding Phase B boot verification and Phase C runtime hardening (automated rollback, read-only `/usr`, credential delivery).

## Roadmap

Priority order. Each item depends on the ones above it.

### Phase A: build path and core artifacts (Complete)

- [x] Extend cluster build deadlines so the pipeline can finish.
- [x] Fix `build.yml` actionlint warnings.
- [x] Confirm build path succeeds and publishes `bluefin-server-installer:latest` to `<registry-host>:30500`.
- [x] Add `oci/k0s-sysext.bst` to the build and validation pipeline.
- [x] Integrate uutils coreutils across OS elements.
- [x] Merge-contract graph validation (`just validate`) passes clean.

### Phase B: automated boot verification (In progress for Alpha)

- [x] Create `bluefin-server-boot-test` Argo workflow in the downstream factory CI repository.
- [ ] Run the workflow against a successful installer build on the lab cluster and iterate to green.
- [ ] Wire the boot test into a post-merge CI gate or CronWorkflow.

### Phase C: update/rollback and provisioning

- [ ] Add `root-b` to installer repart recipes and verify `systemd-sysupdate` stages into the inactive slot.
- [ ] Switch UKI cmdline from `rw` to `ro` and rely on `/var` for mutable state.
- [ ] Consume `systemd-creds` for static network config.
- [ ] Add boot menu entry to select the previous slot after a failed update.

### Phase D: release discipline

- [ ] Tag `v1.0.0-MVP` once Phase B passes.
- [ ] Publish release notes: verified boot path, trust model, known gaps.

## Migration prerequisites

Users of `root / bluefin` must provision the `core` key credential before booting the hardened release, and recovery is offline ESP replacement of `/loader/credentials/tmpfiles.extra.cred`. There is no password or root fallback.

## Open decisions

- Does MVP 1.0 require A/B dual-slot rollback, or is a single-slot signed update with documented reinstall recovery acceptable for the first release?

## Related files

- Downstream factory CI repository Argo workflow templates
- `projectbluefin/server/.github/workflows/build.yml`
- `docs/skills/gap-analysis-distros.md`
- `docs/skills/architecture-roadmap.md`
