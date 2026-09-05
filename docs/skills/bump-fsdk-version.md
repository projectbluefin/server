---
name: bump-fsdk-version
description: Move Bluefin Server to a new freedesktop-sdk release and refresh the derived tags. Use when tracking the FSDK lifecycle or pinning a new FSDK point release.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-09-04
  context7-sources:
    - /apache/buildstream
---
# Bump the FSDK Version

Use when moving to a new FSDK release, or refreshing the pinned ref.

## When to Use

- Moving to a new FSDK point release or minor line.
- Refreshing the pinned `ref:` in `elements/freedesktop-sdk.bst`.
- Verifying or fixing a Renovate point-release PR.

## When NOT to Use

- Application-level versioning questions — there is none; the version axis is
  the FSDK release.
- CI workflow changes to the Renovate handoff itself — see `ci-tooling.md`.

## The version model

There is no application version for these images — the version axis IS the FSDK
release. Tags are derived from the pinned junction ref in
`elements/freedesktop-sdk.bst` (the `ref:` line, e.g.
`freedesktop-sdk-26.08.0-...`):

- `:latest` — rolling, every publish
- `:26.08` — FSDK minor line (moves within the line)
- `:26.08.0` — FSDK point release, treated **immutable**

`just tags` parses these from the ref. Provenance labels
`io.projectbluefin.fsdk.version` / `io.projectbluefin.fsdk.ref` are applied at
export so every image self-declares its base.

## Core Process

1. Find the target ref/tag upstream:
   <https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/releases>
   (or the `freedesktop-sdk-YY.MM` branch tip for a minor line).

2. Update the `ref:` in `elements/freedesktop-sdk.bst` to the new tag/commit,
   and set `release-version` in `project.conf` to the same point release.
   `just check-version` fails the build while the two disagree. (On Renovate
   PRs the `build.yml` track-and-resolve step re-syncs `project.conf`
   automatically; manual bumps must update both files.)

3. Re-check patches still apply — FSDK ships local patches under
   `patches/freedesktop-sdk/`. If a release changed the patched files, refresh or
   drop them. `just validate` surfaces patch failures.

4. Rebuild and verify:

   ```
   just validate
   just tags        # confirm derived tags look right
   just build-installer
   just build-ddi
   ```

   `elements/bluefin-server/os-release-flatcar.bst` reads the FSDK point release
directly from `elements/freedesktop-sdk.bst`, so `NAME`, `PRETTY_NAME`, and
   `IMAGE_VERSION` update automatically.

5. Follow the FSDK lifecycle: track the active minor line; when FSDK EOLs a
   line, move `:latest` to the next supported minor. Don't pin to an EOL line.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Renovate handles bumps, so I can ignore the ref format." | Renovate only automates point releases; minor-line moves and patch refreshes are manual. |
| "Updating the `ref:` is enough." | `release-version` in `project.conf` must match or `just check-version` fails the build. |
| "The patches applied last time." | Any FSDK release can touch the patched files; re-check `patches/freedesktop-sdk/` every bump. |

## Red Flags

- `ref:` in `elements/freedesktop-sdk.bst` and `release-version` in
  `project.conf` disagreeing.
- Patch failures in `just validate` after a bump.
- Republishing different bits under an already-published point-release tag.
- Junction overrides for components no local element references.

## Verification

Before merging a bump:

- [ ] `just validate` passes (element graph resolves with new ref)
- [ ] `just tags` output matches the expected `latest / YY.MM / YY.MM.PP` triple
- [ ] `just build-installer` and `just build-ddi` complete without error
- [ ] `io.projectbluefin.fsdk.version` label on the built image matches the new FSDK version

- Bumping across a minor line may rename or relocate components.
  Re-confirm `components/*` names against the staged junction before assuming a
  dependency still exists.
- A point-release tag is immutable: once `:26.08.0` is published, never republish
different bits under it.
- Keep the FSDK junction vanilla. Add a local patch only for a demonstrated
  Server requirement, and keep it scoped to that requirement.

## Automated Point-Release Bumps

Point releases are fully automated via Renovate and GitHub Actions.
- **Trigger:** Renovate bot scans `elements/freedesktop-sdk.bst` using a custom regex manager. When a new upstream point release is published, Renovate creates a Pull Request.
- **Mechanism:** On the Renovate PR, a GHA job in `build.yml` automatically runs `just bst source track freedesktop-sdk.bst` to track and resolve the raw tag to the full `git-describe` ref, re-syncs `release-version` in `project.conf` to the same point release, then commits and pushes both back to the PR branch.
- **Build Loop:** When the PR is merged to `main`, GitHub Actions automatically compiles the standalone DDI OS and installer images, and publishes them directly to GitHub Releases under the new FSDK point-release version.
