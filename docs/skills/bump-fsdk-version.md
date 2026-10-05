---
name: bump-fsdk-version
description: Move Bluefin Server to a new freedesktop-sdk release and refresh the derived tags. Use when tracking the FSDK lifecycle or pinning a new FSDK point release.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-10-03"
  context7-sources:
    - /apache/buildstream
---
# Bump the FSDK Version

Use when moving to a new FSDK release, or refreshing the pinned ref.

## The version model

There is no application version for these images. Two version axes exist:

- `installer-version` in `project.conf` tracks the pinned FSDK point release
  (the `ref:` line in `elements/freedesktop-sdk.bst`, e.g.
  `freedesktop-sdk-26.08.0-...`). `.github/scripts/check-release-version.py`
  fails closed on drift between the two, and is the one parser of that point
  release: `--print-fsdk` prints it (the Justfile's `fsdk_version`), `--fix`
  syncs `installer-version` to it before checking.
- `image-version` in `include/image.yml` is the per-build OS version shared by
  the usr DDI, the UKIs, and sysupdate transfers. CI sets it with
  `just set-version` (`YY.MM.<run>` on main, `0.<run>` on PRs);
  `systemd-sysupdate` orders it with `strverscmp()`, so keep it monotonic and
  at most 17 characters.

`just version` / `just tags` print the FSDK-derived point release and tag set
(`latest`, minor line, point release), from `check-release-version.py --print-fsdk`.

## Procedure

1. Find the target ref/tag upstream:
   <https://gitlab.com/freedesktop-sdk/freedesktop-sdk/-/releases>
   (or the `freedesktop-sdk-YY.MM` branch tip for a minor line).

2. Update the `ref:` in `elements/freedesktop-sdk.bst` to the new tag/commit.

3. Re-check the local patches in `patches/freedesktop-sdk/`
   ([`patches/README.md`](../../patches/README.md) says why each exists and
   when to drop it). `just validate` surfaces a patch that no longer applies.

4. Rebuild and verify:

   ```
   just validate
   just tags        # confirm derived tags look right
   just build-image
   ```

   `elements/bluefin-server/os-release.bst` reads `image-version` from
   `include/image.yml`, so `NAME`, `PRETTY_NAME`, and `IMAGE_VERSION` update
   automatically on the next build.

5. Follow the FSDK lifecycle: track the active minor line; when FSDK EOLs a
   line, move `:latest` to the next supported minor. Don't pin to an EOL line.

## Verification

Before merging a bump:

- [ ] `just validate` passes (element graph resolves with new ref)
- [ ] `just tags` output matches the expected `latest / YY.MM / YY.MM.PP` triple
- [ ] All patches in `patches/freedesktop-sdk/` apply cleanly (no patch failure in `just validate`)
- [ ] `just build-image` completes without error
- [ ] The built image's `/usr/lib/os-release` carries the new `image-version`

- Bumping across a minor line (for example, 25.08 → 26.08) may rename/relocate components or restructure runtime stacks:
  - In FSDK 26.08, `public-stacks/runtime-minimal.bst` drops bash and coreutils, which moved to `public-stacks/runtime-gnu.bst`. Stacks whose components carry shell integration commands (like `elements/base/base-stack.bst` for `ldconfig` and `ca-certificates`) need `public-stacks/runtime-gnu.bst` in `depends:`.
  - `components/systemd-base.bst` was dropped in FSDK 26.08, and FSDK now ships its own systemd directly.
- `freedesktop-sdk.bst` is the only junction. `project.conf` takes FSDK's
  `include/runtime.yml` and the `collect_initial_scripts` plugin straight from
  it; there is no gnome-build-meta junction to keep in step.
- A point-release tag is immutable: once a GitHub Release for a given
  `image-version` is published, never republish different bits under it.
- **Three patches live under `patches/freedesktop-sdk/`.** `0001` adds the GNOME
  CAS servers to `project.conf`; **`0006`
  carries the Cilium/Kubernetes kernel options** (VXLAN, GENEVE, tc BPF,
  conntrack/ss diagnostics) and `0007` the hardware watchdog core and drivers,
  appended below `0006` in the same `fdsdk-config.sh`. A bumper must not drop `0006` or the kubeadm and
  k0s sysexts lose their datapath. If a release changed a patched file,
  refresh the patches in place, `0006` before `0007`; never delete `0006` because "it looks small". Why each patch exists and when it can be dropped is in
  [`patches/README.md`](../../patches/README.md).
- Junction overrides are only meaningful for components your local elements
  reference directly. The 25 GNOME sdk/* overrides (cairo, gtk3, pango, glib,
  gdk-pixbuf…) were dead weight — none of our `base-stack`, `brew-deps` etc. ever
  reference those components. If you copy a junction from another repo in the
  future, strip every override whose component is not in your local dep graph.

## Automated Point-Release Bumps

Point releases are delivered by the scheduled `track-junctions.yml` workflow.
- **Trigger:** `track-junctions.yml` runs daily and resolves the junction's own `track: freedesktop-sdk-26.08*` glob; it does not wait on a Renovate PR.
- **Mechanism:** `track-junctions.yml` runs `just bst source track freedesktop-sdk.bst`, syncs `project.conf`'s `installer-version` to the tracked point release (`check-release-version.py --fix`), and opens or updates its own PR on `auto/track-junctions` through `.github/scripts/propose-pr.sh`, which leaves an open PR alone when it already proposes the same refs. It never runs on `pull_request`, so a junction bump can never be injected into an unrelated dependency PR.
- **Build Loop:** When the PR is merged to `main`, GitHub Actions compiles the image set (OS DDI, UKIs, netboot ESP) and sysexts, and publishes them to a new GitHub Release tagged `v<image-version>`.

## See also

- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
