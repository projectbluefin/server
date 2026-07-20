# Bluefin Server MVP 1.0 Readiness Audit

This audit tracks the gap between the current tree and a first public/usable MVP 1.0 release.

## MVP 1.0 bar

1. **Reproducible build path** — documented command or CI job that produces the DDI, live installer, and k3s sysext.
2. **Signed release artifacts** — combined `SHA256SUMS` + detached GPG signature published to GitHub Releases.
3. **Automated boot verification** — at least one non-human test that proves the installer writes a bootable disk and the installed OS reaches a target.
4. **Functional update path** — host can pull the signed manifest and apply an OS update without manual intervention.
5. **Basic first-boot provisioning** — unattended way to set root credential and drop an SSH authorized key.
6. **Documented recovery** — A/B rollback or reinstall-from-media path for a failed update.

## Current state

| Check | Status | Evidence |
|---|---|---|
| Element graph resolves | ✅ | `just validate` succeeds for DDI, installer, and k3s sysext |
| Release workflow lint | ✅ | `actionlint .github/workflows/build.yml` clean |
| Release path exists | ✅ | `.github/workflows/build.yml` builds, signs, uploads to GitHub Release |
| Cluster build pipeline | ✅ | Deadlines fixed in the downstream factory CI repository; branch build running |
| Automated boot test | ✅ | `bluefin-server-boot-test` Argo workflow created in the downstream factory CI repository; pending a successful branch build to run |
| A/B root rollback | ❌ | `50-root.transfer` names `root-a`/`root-b`, installer only creates `root-a` |
| Root immutability | ❌ | DDI boots read/write (`rw` on cmdline) |
| First-boot SSH keys | ❌ | Only root password credential path exists |

Competitor context: [gap-analysis-distros.md](skills/gap-analysis-distros.md)

## Verdict

**Not ready for MVP 1.0.** The build, release, and boot-test plumbing are in place, but the runtime still lacks automated rollback, read-only `/usr`, and complete first-boot credential delivery.

## Roadmap

Priority order. Each item depends on the ones above it.

### Phase A: prove the build path

- [x] Extend cluster build deadlines so the pipeline can finish.
- [x] Fix `build.yml` actionlint warnings.
- [ ] Confirm a branch build succeeds and publishes `bluefin-server-installer:latest` to lab Zot.
- [ ] Add `oci/k3s-sysext.bst` to the cluster build pipeline.

### Phase B: automated boot verification

- [x] Create `bluefin-server-boot-test` Argo workflow in the downstream factory CI repository.
- [ ] Run the workflow against a successful installer build and iterate to green.
- [ ] Wire the boot test into a post-merge CI gate or CronWorkflow.

### Phase C: update/rollback and provisioning

- [ ] Add `root-b` to installer repart recipes and verify `systemd-sysupdate` stages into the inactive slot.
- [ ] Switch UKI cmdline from `rw` to `ro` and rely on `/var` for mutable state.
- [ ] Consume `systemd-creds` for SSH authorized keys and static network config.
- [ ] Add boot menu entry to select the previous slot after a failed update.

### Phase D: release discipline

- [ ] Tag `v1.0.0-MVP` once Phase B passes.
- [ ] Publish release notes: verified boot path, trust model, known gaps.

## Open decisions

- Does MVP 1.0 require A/B dual-slot rollback, or is a single-slot signed update with documented reinstall recovery acceptable for the first release?

## Related files

- Downstream factory CI repository Argo workflow templates
- `projectbluefin/server/.github/workflows/build.yml`
- `docs/skills/gap-analysis-distros.md`
- `docs/skills/architecture-roadmap.md`
