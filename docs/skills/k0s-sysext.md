---
name: k0s-sysext
description: Build and ship the k0s systemd-sysext for Bluefin Server. KubeStellar / Argo CD / kiosk live in the separate oci/kubestellar-sysext.bst.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-28"
  context7-sources:
    - /systemd/systemd
---
# k0s systemd-sysext

Use this skill when working on the k0s systemd-sysext extension shipped as an
optional overlay for Bluefin Server.

## When to Use

- Bumping the pinned k0s binary version or its SHA256.
- Modifying the k0s sysext image contents (`files/k0s/sysext/`).
- Changing the k0s controller or worker systemd units.
- Adding or changing the sysupdate transfer definition
  (`files/os/sysupdate.k0s.d/70-k0s.transfer`).
- Debugging why a host cannot pull, merge, or start k0s.

## When NOT to Use

- Building or shipping the KubeStellar / Argo CD appliance; that is the separate
  `oci/kubestellar-sysext.bst` (see `k0s-sysext-ops.md` for the split).
- General OS image composition questions (use `ddi-installer.md` or `avoid-over-engineering.md`).
- systemd-sysupdate signature verification (use `systemd-sysupdate-verification.md`).

## Architecture

Bluefin Server's base /usr image includes bash for login and bring-up, while
heavy developer and debug tools live in sysexts or system containers. k0s is not
baked into the OS stack. Instead it is delivered as a `systemd-sysext` EROFS
image that overlays `/usr` at runtime.

The k0s sysext contains only:

- `/usr/bin/k0s`
- `k0scontroller.service`
- `k0sworker.service`

Design choices:

- **Single static binary.** `elements/k0s/k0s-bin.bst` fetches the upstream
  statically-linked release binary directly from GitHub.
- **Controller by default.** `k0scontroller.service` runs unless
  `/etc/k0s/token` exists; then `k0sworker.service` starts instead and the node
  joins the cluster with that token. Both units use
  `ConditionPathExists=!/etc/k0s/token` and `ConditionPathExists=/etc/k0s/token`
  respectively, so only one is active.
- **Overridable controller args.** The controller unit defaults to
  `--enable-worker --single --disable-components=helm,autopilot` (single-node,
  no Helm). Set `K0S_CONTROLLER_ARGS` in `/etc/sysconfig/k0s` to override.
- **Identity.** The extension uses `ID=_any` in its release metadata so it
  merges on any host image.
- **Opt-in activation.** `k0s-first-boot.service` is explicitly disabled in
  `80-bluefin-opt-in.preset`. An operator opts in by placing `k0s.raw` at
  `/var/lib/k0s/k0s.raw` (or letting `k0s-first-boot-fetch.service` run
  `sysupdate --component=k0s`) and then running
  `systemctl enable --now k0s-first-boot.service`. The unit copies the image to
  `/run/extensions/k0s.raw`, runs `systemd-sysext refresh`, and enables the
  controller or worker.
- **Why the activation units stay in the base image.** A sysext cannot
  activate itself: nothing in it runs until something merges it, and the k0s
  image lives in `/var/lib/k0s`, outside the extension directories
  `systemd-sysext` scans. `k0s-first-boot.service` (and its fetcher) is that
  something, so it ships in `/usr` (`bluefin-server/os-k0s-first-boot.bst`).
  A provisioner such as [Booty](https://github.com/jeefy/booty) or an
  Ignition config writes `/var/lib/k0s/k0s.raw` and enables the unit. It is
  inert otherwise: FSDK has no catch-all `disable *` preset, so
  `80-bluefin-opt-in.preset` disables both units explicitly, and no preset in
  the image or in any sysext enables them.
- **OTA delivery.** A k0s component `systemd-sysupdate` transfer file
  (`70-k0s.transfer`) is installed in the base OS so hosts can pull new k0s
  sysext releases from GitHub Releases without updating the root or UKI.

## Repository Layout

| Path | Purpose |
|------|---------|
| `include/k0s.yml` | **Single source of truth for the k0s version axis** (`%{k0s-upstream-tag}`, `%{k0s-version}`). |
| `elements/k0s/k0s-bin.bst` | Pins the upstream `k0s` binary SHA256; the release URL is derived from `include/k0s.yml`. |
| `elements/oci/k0s-sysext.bst` | Builds the EROFS sysext image (`k0s-<k0s-version>.raw`). |
| `elements/oci/kubestellar-sysext.bst` | Separate opt-in sysext with Argo CD, KubeStellar, kiosk, and kubeflex secret generators. |
| `files/k0s/sysext/k0scontroller.service` | systemd unit for the k0s controller. Not enabled by default. |
| `files/k0s/sysext/k0sworker.service` | systemd unit for the k0s worker; selected by `/etc/k0s/token`. |
| `files/k0s/sysext/extension-release.k0s` | Static sysext identity (`ID=_any`); `VERSION_ID=`/`ARCHITECTURE=` are appended at build time. |
| `files/os/sysupdate.k0s.d/70-k0s.transfer` | sysupdate transfer track for the k0s sysext component. |
| `files/os/systemd/system/k0s-first-boot.service` | One-shot unit that merges the k0s sysext and starts the correct role. |
| `files/os/systemd/system/k0s-first-boot-fetch.service` | Fetches the k0s sysext via sysupdate when `/var/lib/k0s/k0s.raw` is missing. |
| `files/os/systemd/system-preset/80-bluefin-opt-in.preset` | Disables `k0s-first-boot.service` and `k0s-first-boot-fetch.service` by default. |
| `Justfile` | `build-sysext` / `export-sysext` targets. |
| `.github/workflows/build.yml` | Builds, signs, and publishes sysext assets. |
| `.github/scripts/check-k0s-version.py` | Fails closed if any consumer restates the k0s version instead of deriving it. |
| `.github/scripts/track-binaries.py` | Moves both atoms and the SHA256 together: `track-binaries.yml` proposes patch releases of the pinned minor, `apply k0s --version X.Y.Z+k0s.N` makes a minor bump by hand (then move the series in `tests/unit/test_k0s_version.py`). |

## Build Outputs

`elements/oci/k0s-sysext.bst` produces:

- `k0s-<k0s-version>.raw` — uncompressed EROFS sysext image.
- `k0s-<k0s-version>.raw.zst` — zstd-compressed release asset.
- `SHA256SUMS` — checksum manifest for the compressed asset.

## Justfile Commands

```bash
just validate              # resolve the element graph
just build-sysext          # build oci/k0s-sysext.bst + oci/kubestellar-sysext.bst
just export-sysext         # export both sysext artifacts to dist/sysext/
```

## Operations and runtime testing

For enabling the sysext on a host, common gotchas, and runtime testing guidance,
see [k0s-sysext-ops.md](k0s-sysext-ops.md).

## See also

- [k0s-sysext-ops.md](k0s-sysext-ops.md)
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Sysext definition).
- `systemd-sysext(8)`, `systemd-confext(8)`
