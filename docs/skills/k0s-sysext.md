---
name: k0s-sysext
description: Build, ship, and enable the k0s systemd-sysext extension with native Argo CD & KubeStellar for Bluefin Server.
metadata:
  type: how-to
  status: stable
  last_updated: "2026-09-07"
  context7-sources:
    - /systemd/systemd
---
# k0s systemd-sysext

Use this skill when working on the k0s systemd-sysext extension shipped as an
optional overlay for Bluefin Server.

## When to Use

- Bumping the pinned k0s binary version or its SHA256.
- Modifying the sysext image contents (`files/k0s/sysext/`).
- Managing raw YAML manifest stacks (`files/k0s/manifests/argocd/` or `files/k0s/manifests/kubestellar/`).
- Changing manifest seeding rules in `files/k0s/sysext/k0s-manifests.conf`.
- Adding or changing the sysupdate transfer definition (`files/os/sysupdate.d/70-k0s.transfer`).
- Debugging why a host cannot pull, merge, or start k0s.

## When NOT to Use

- General OS image composition questions (use `ddi-installer.md` or `avoid-over-engineering.md`).
- systemd-sysupdate signature verification (use `systemd-sysupdate-verification.md`).

## Architecture

Bluefin Server's base DDI image is distroless and read-only. k0s is not baked
into the OS stack. Instead it is delivered as a `systemd-sysext` EROFS image
that overlays `/usr` at runtime.

Design choices:

- **Single static binary.** `elements/k0s/k0s-bin.bst` fetches the upstream statically-linked
  release binary directly from GitHub.
- **Pure declarative manifests (No Helm).** Declarative stacks for Argo CD and KubeStellar
  are shipped in `/usr/share/k0s/manifests/` and seeded into `/var/lib/k0s/manifests/` via
  `systemd-tmpfiles`. k0s's internal manifest deployer automatically reconciles them.
- **Helm disabled.** `--disable-components=helm` ensures zero runtime Helm dependencies.
- **Flatcar sysext pattern.** The extension uses `ID=_any` in its release metadata so it merges on any host image.
- **OTA delivery.** A `systemd-sysupdate` transfer file (`70-k0s.transfer`) is installed in the base OS so hosts can pull new k0s sysext releases from GitHub Releases.

## Repository Layout

| Path | Purpose |
|------|---------|
| `include/k0s.yml` | **Single source of truth for the k0s version axis** (`%{k0s-upstream-tag}`, `%{k0s-version}`). |
| `elements/k0s/k0s-bin.bst` | Pins the upstream `k0s` binary SHA256; the release URL is derived from `include/k0s.yml`. |
| `elements/oci/k0s-sysext.bst` | Builds the EROFS sysext image (`k0s-<k0s-version>.raw`). |
| `files/k0s/sysext/k0scontroller.service` | systemd unit for the k0s single-node controller/worker. Not enabled by default. |
| `files/k0s/sysext/extension-release.k0s` | Static sysext identity (`ID=_any`); `VERSION_ID=`/`ARCHITECTURE=` are appended at build time. |
| `files/k0s/sysext/k0s-manifests.conf` | tmpfiles rule that copies declarative stacks to `/var/lib/k0s/manifests/`. |
| `files/k0s/manifests/argocd/` | Raw YAML manifests for Argo CD. |
| `files/k0s/manifests/kubestellar/` | Raw YAML manifests for KubeFlex, Postgres, KubeStellar core, and Console. |
| `files/os/sysupdate.d/70-k0s.transfer` | sysupdate transfer track for the k0s sysext. |
| `Justfile` | `build-sysext` / `export-sysext` targets. |
| `.github/workflows/build.yml` | Builds, signs, and publishes sysext assets. |
| `.github/scripts/check-k0s-version.py` | Fails closed if any consumer restates the k0s version instead of deriving it. |

## Build Outputs

`elements/oci/k0s-sysext.bst` produces:

- `k0s-<k0s-version>.raw` — uncompressed EROFS sysext image.
- `k0s-<k0s-version>.raw.zst` — zstd-compressed release asset.
- `SHA256SUMS` — checksum manifest for the compressed asset.

## Justfile Commands

```bash
just validate              # resolve the element graph
just build-sysext          # build oci/k0s-sysext.bst
just export-sysext         # export sysext artifacts to dist/sysext/
```

## Operations and runtime testing

For enabling the sysext on a host, common gotchas, and runtime testing guidance,
see [k0s-sysext-ops.md](k0s-sysext-ops.md).

## See also

- [k0s-sysext-ops.md](k0s-sysext-ops.md)
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary (Sysext definition).
- `systemd-sysext(8)`, `systemd-confext(8)`
