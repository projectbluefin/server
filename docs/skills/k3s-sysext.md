---
name: k3s-sysext
description: Build, ship, and enable the k3s systemd-sysext extension for Bluefin Server.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-07-20
  context7-sources:
    - /systemd/systemd
---
# k3s systemd-sysext

Use this skill when working on the k3s systemd-sysext extension shipped as an
optional overlay for Bluefin Server.

## When to Use

- Bumping the pinned k3s binary version or its SHA256.
- Modifying the sysext image contents (`files/k3s/sysext/`).
- Changing k3s tuning defaults or how they are seeded into `/etc/rancher/k3s/`.
- Adding or changing the sysupdate transfer definition
  (`files/os/sysupdate.d/70-k3s.transfer`).
- Debugging why a host cannot pull, merge, or start k3s.

## When NOT to Use

- General OS image composition questions (use `ddi-installer.md` or
  `avoid-over-engineering.md`).
- systemd-sysupdate signature verification (use
  `systemd-sysupdate-verification.md`).
- Kubernetes workload or cluster architecture questions outside the sysext
  packaging.

## Architecture

Bluefin Server's base DDI image is distroless and read-only. k3s is not baked
into the OS stack. Instead it is delivered as a `systemd-sysext` EROFS image
that overlays `/usr` at runtime. This keeps the base DDI small and lets
operators opt into Kubernetes on a per-host basis.

Design choices:

- **BST-pure build.** `elements/k3s/k3s-bin.bst` fetches the upstream release
  binary directly from GitHub; the get.k3s.io installer is not used.
- **Neutral tuning only.** The sysext ships a small set of controller/kubelet
  timing defaults in `/usr/share/bluefin/k3s/50-bluefin-tuning.yaml` and seeds
  them into `/etc/rancher/k3s/config.yaml.d/` with a tmpfiles rule.
- **Role chosen at provisioning time.** Both `k3s.service` and
  `k3s-agent.service` are installed inside the sysext, but neither is enabled.
- **Flatcar sysext pattern.** The extension uses `ID=_any` in its release
  metadata so it merges on any host image.
- **OTA delivery.** A `systemd-sysupdate` transfer file is installed in the base
  OS so hosts can pull new k3s sysext releases from GitHub Releases.

## Repository Layout

| Path | Purpose |
|------|---------|
| `include/k3s.yml` | **Single source of truth for the k3s version axis** (`%{k3s-upstream-tag}`, `%{k3s-version}`). |
| `elements/k3s/k3s-bin.bst` | Pins the upstream `k3s` binary SHA256; the release URL is derived from `include/k3s.yml`. |
| `elements/oci/k3s-sysext.bst` | Builds the EROFS sysext image (`k3s-<k3s-version>.raw`). |
| `files/k3s/sysext/k3s.service` | systemd unit for the k3s server. Not enabled. |
| `files/k3s/sysext/k3s-agent.service` | systemd unit for the k3s agent. Not enabled. |
| `files/k3s/sysext/extension-release.k3s` | Static sysext identity (`ID=_any`); `VERSION_ID=`/`ARCHITECTURE=` are appended at build time. |
| `files/k3s/sysext/50-bluefin-tuning.yaml` | Bluefin tuning defaults shipped in `/usr`. |
| `files/k3s/sysext/k3s-bluefin.conf` | tmpfiles rule that copies tuning defaults to `/etc`. |
| `files/os/sysupdate.d/70-k3s.transfer` | sysupdate transfer track for the k3s sysext. |
| `Justfile` | `build-sysext` / `export-sysext` targets. |
| `.github/workflows/build.yml` | Builds, signs, and publishes sysext assets. |
| `.github/scripts/check-k3s-version.py` | Fails closed if any consumer restates the k3s version instead of deriving it. |

## Build Outputs

`elements/oci/k3s-sysext.bst` produces:

- `k3s-<k3s-version>.raw` — uncompressed EROFS sysext image.
- `k3s-<k3s-version>.raw.zst` — zstd-compressed release asset.
- `SHA256SUMS` — checksum manifest for the compressed asset.

`<k3s-version>` is `%{k3s-version}` from `include/k3s.yml` — the upstream k3s
release in filename-safe form (`v1.36.2+k3s1` → `1.36.2-k3s1`; GitHub rewrites
`+` in release asset names). The artifact filename is keyed to the **k3s**
version, not the OS release version, because `70-k3s.transfer` reads that
filename through `@v` as the version of the thing it delivers. A k3s bump
therefore ships on its own, and an OS point release no longer renames a
byte-identical sysext.

## Justfile Commands

```bash
just validate              # resolve the element graph
just build-sysext          # build oci/k3s-sysext.bst
just export-sysext         # export sysext artifacts to dist/sysext/
```

## Bumping the k3s Version

Two places must change together when the upstream k3s release moves:

1. **The version atoms** `k3s-k8s-version` and `k3s-patch` in `include/k3s.yml`.
   Every other spelling — the download URL, the release asset filename, and the
   `VERSION_ID=` in the extension-release metadata — is derived from these.
2. **The checksum** `ref:` in `elements/k3s/k3s-bin.bst`, taken from the new
   release's `sha256sum-amd64.txt` asset.

After updating these values, run `just validate` (which runs
`.github/scripts/check-k3s-version.py`) to confirm the version invariant holds
and the element graph still resolves.

## Operations and runtime testing

For enabling the sysext on a host, common gotchas, and runtime testing guidance,
see [k3s-sysext-ops.md](k3s-sysext-ops.md).

## Verification

- [ ] `include/k3s.yml` is the only file naming a k3s version; the URL in
      `elements/k3s/k3s-bin.bst` derives from `%{k3s-upstream-tag}` and carries
      a matching SHA256.
- [ ] `files/k3s/sysext/extension-release.k3s` has `ID=_any` and no literal
      `VERSION_ID=` (it is appended from `%{k3s-version}` at build time).
- [ ] `python3 .github/scripts/check-k3s-version.py` passes.
- [ ] Both `k3s.service` and `k3s-agent.service` are present and neither is
      enabled by default.
- [ ] `files/os/sysupdate.d/70-k3s.transfer` uses a static `Path=` and `@v`
      patterns matching the k3s-axis asset name, plus `CurrentSymlink=k3s.raw`.
- [ ] `just validate` resolves the element graph after any k3s version bump.
- [ ] `just build-sysext && just export-sysext` produces the expected artifacts.

## See also

- [k3s-sysext-ops.md](k3s-sysext-ops.md)
- `systemd-sysext(8)`, `systemd-confext(8)`
