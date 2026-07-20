---
name: bump-fsdk-version
version: "1.0"
last_updated: "2026-07-20"
tags: ['fsdk', 'versioning', 'release']
description: "Move Bluefin Server to a new freedesktop-sdk release and refresh the derived tags. Use when tracking the FSDK lifecycle or pinning a new FSDK point release."
metadata:
  context7-sources:
    - /apache/buildstream
---

# Bump the FSDK Version

Use when moving to a new FSDK release, or refreshing the pinned ref.

## The version model

There is no application version for these images — the version axis IS the FSDK
release. Tags are derived from the pinned junction ref in
`elements/freedesktop-sdk.bst` (the `ref:` line, e.g.
`freedesktop-sdk-25.08.13-...`):

- `:latest` — rolling, every publish
- `:25.08` — FSDK minor line (moves within the line)
- `:25.08.13` — FSDK point release, treated **immutable**

`just tags` parses these from the ref. Provenance labels
`io.projectbluefin.fsdk.version` / `io.projectbluefin.fsdk.ref` are applied at
export so every image self-declares its base.

## Procedure

1. Find the target ref/tag upstream:
   <https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/releases>
   (or the `freedesktop-sdk-YY.MM` branch tip for a minor line).

2. Update the `ref:` in `elements/freedesktop-sdk.bst` to the new tag/commit.

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

5. Follow the FSDK **lifecycle**: track the active minor line; when FSDK EOLs a
   line, move `:latest` to the next supported minor. Don't pin to an EOL line.

## Verification

Before merging a bump:

- [ ] `just validate` passes (element graph resolves with new ref)
- [ ] `just tags` output matches the expected `latest / YY.MM / YY.MM.PP` triple
- [ ] Both `patches/freedesktop-sdk/` patches (`0001`, `0002`) applied cleanly (no patch failure in `just validate`)
- [ ] `just build-installer` and `just build-ddi` complete without error
- [ ] `io.projectbluefin.fsdk.version` label on the built image matches the new FSDK version

- Bumping across a minor line (e.g. 25.08 → 26.08) may rename/relocate components.
  Re-confirm `components/*` names against the staged junction before assuming a
  dep still exists.
- A point-release tag is immutable: once `:25.08.13` is published, never republish
  different bits under it.
- **Only the systemd-* overrides and two CAS-config patches remain.** When Dakota
  syncs a new FSDK pin, check whether `patches/freedesktop-sdk/0001` and `0002`
  (CAS limits + GNOME CAS servers) still apply cleanly. All other dakota patches
  (openssh, lvm2, pipewire, cross-compilers, frei0r, kernel-v3) were stripped
  because this repo never builds those components.
- **Junction overrides are only meaningful for components your local elements
  reference directly.** The 25 GNOME sdk/* overrides (cairo, gtk3, pango, glib,
  gdk-pixbuf…) were dead weight — none of our `base-stack`, `brew-deps` etc. ever
  reference those components. If you copy a junction from dakota in the future,
  strip every override whose component is not in your local dep graph.

## Automated Point-Release Bumps

Point releases are fully automated via Renovate and GitHub Actions.
- **Trigger:** Renovate bot scans `elements/freedesktop-sdk.bst` using a custom regex manager. When a new upstream point release is published, Renovate creates a Pull Request.
- **Mechanism:** On the Renovate PR, a GHA job in `build.yml` automatically runs `just bst source track freedesktop-sdk.bst` to track and resolve the raw tag to the full `git-describe` ref, then commits and pushes it back to the PR branch.
- **Build Loop:** When the PR is merged to `main`, GitHub Actions automatically compiles the standalone DDI OS and installer images, and publishes them directly to GitHub Releases under the new FSDK point-release version.


