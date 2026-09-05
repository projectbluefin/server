### Story e01s01: Enforce one release version and tag contract

**type:** fix
**risk:** P0
**context:** infra

## Context

The FSDK junction, `project.conf`, artifact names, sysupdate match patterns,
and GitHub release tag must identify the same release. The existing workflow
could publish a `bluefin-server-v26.08.0` tag containing mismatched assets.

## Requirements

- **MODIFIED** — Before: the FSDK ref, BuildStream release version, and release
  tag could diverge silently. After: `just check-version` fails on malformed or
  mismatched release identities, and CI runs it before graph validation.
- **MODIFIED** — Before: releases used the `installer-v<version>` namespace.
  After: releases use `bluefin-server-v<version>`.

## Steps

1. Make `project.conf` match the pinned FSDK point release and add the shared
   version check → verify: `just check-version`
2. Make `validate` and CI invoke the version check before graph resolution →
   verify: `just validate`
3. Generate releases in the `bluefin-server-v<version>` namespace → verify:
   `actionlint .github/workflows/build.yml`

## Verification Script

1. Run `just check-version` and confirm it exits 0 (it is silent on success
   and fails closed on drift).
2. Run `just version` and confirm it prints `26.08.0`.
3. Inspect the workflow tag expression and confirm it is
   `bluefin-server-v${V}`.

## Out of scope

- Changing the FSDK release cadence or introducing a second application
  version axis.

## Risks

- Future FSDK bumps must update the BuildStream release variable in the same
  change; the check intentionally makes drift fail fast. Renovate PRs do this
  automatically: the `build.yml` track-and-resolve step re-syncs
  `project.conf` before `just check-version` runs.
