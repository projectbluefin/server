---
name: signing-and-sbom
description: BuildStream-native SPDX SBOM generation and release signing for Bluefin Server. Use when auditing, debugging, or extending SBOM generation, the release SHA256SUMS signing pipeline, or vulnerability scanning.
metadata:
  type: how-to
  status: stable
  last_updated: 2026-09-04
---
# Signing and SBOM

Bluefin Server publishes SPDX 2.3 SBOMs for all three release artifacts
(DDI payload, installer, k3s sysext) alongside the signed `SHA256SUMS`
manifest.

## When to Use

- Auditing, debugging, or extending SBOM generation.
- Changing the release `SHA256SUMS` signing pipeline in `build.yml`.
- Working on the Grype vulnerability-scan workflow.

## When NOT to Use

- `systemd-sysupdate` transfer or keyring questions — see
  `systemd-sysupdate-verification.md`.
- General CI conventions (SHA pinning, permissions) — see `ci-tooling.md`.

## Why BuildStream-native SBOMs

The shipped images have no RPM/dpkg database, so post-hoc rootfs scanners
(Syft, Trivy) report ~1 package — nothing useful. SBOMs here are generated
from the BuildStream build graph with
[`buildstream-sbom`](https://pypi.org/project/buildstream-sbom/), which
captures every element, its exact source refs, and patch levels from the
pinned FSDK metadata. Never substitute a rootfs scanner.

## Core Process

### Local runbook

```bash
# Generate the SBOM for one artifact (bluefin-server-ddi,
# bluefin-server-installer, or k3s)
just sbom bluefin-server-ddi

# Generate all three in one container run
just sboms

# Inspect
jq '.packages | length' bluefin-server-ddi-*.spdx.json
jq -r '.packages[].name' bluefin-server-ddi-*.spdx.json | grep -E 'glibc|openssl'
```

`buildstream-sbom` is installed inside the pinned `bst2` container at run
time, pinned to a git commit hash (see the `sbom` recipe in the `Justfile`).
Bump it deliberately, never to a branch.

### Release pipeline

In `.github/workflows/build.yml` (main branch only):
1. `just sboms` runs after the three export steps and writes
   `<artifact>-<version>.spdx.json` at the repo root (gitignored).
2. The signing step copies `*.spdx.json` into `dist/release/`, so each SBOM
   is covered by the combined `SHA256SUMS` and its detached
   `SHA256SUMS.gpg` (see `systemd-sysupdate-verification.md`).
3. `.github/scripts/verify-release.py` requires the three `*.spdx.json`
   files — a release without SBOMs fails before signing.
4. Everything in `dist/release/` is uploaded to the
   `bluefin-server-v<version>` GitHub Release.

Each SBOM gets a unique SPDX namespace:
`https://github.com/projectbluefin/server/sbom/<git-sha>/<artifact>`.

### Vulnerability scanning

`.github/workflows/vulnerability-scan.yml` (weekly + manual) downloads the
release SBOMs and scans them with Grype, uploading SARIF to code scanning.
The scan consumes the SBOM, never the image — a missing SBOM asset is a
publish bug, not a scanner quirk. The scan is report-only
(`fail-build: false`): FSDK CVEs are fixed upstream in freedesktop-sdk, and
a newly disclosed CVE must not fail a scheduled scan of an already-shipped
release.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "Scan the `.raw` images with Syft/Trivy." | There is no package database in the distroless images; rootfs scanners report ~1 package. SBOMs come from the BuildStream graph. |
| "Bump `buildstream-sbom` to the latest branch." | It is pinned to a git commit hash in the `Justfile`; bump deliberately, never to a branch. |
| "Make the weekly scan fail on new CVEs." | The scan is report-only; FSDK CVEs are fixed upstream and a new disclosure must not fail a scan of an already-shipped release. |

## Red Flags

- Any proposal to scan the `.raw` images with a rootfs scanner instead of
  the SBOM.
- SBOMs uploaded outside `dist/release/` (they would escape the signed
  manifest).
- Unpinned `buildstream-sbom` installs (branch or bare `pip install`).
- Making the scheduled vulnerability scan fail the build.

## Verification

- [ ] `just sboms` produces three `*.spdx.json` files with non-trivial
      package counts (`jq '.packages | length'`).
- [ ] `python3 .github/scripts/verify-release.py --version "$(just version)"
      --directory dist/release` passes with SBOMs present.
- [ ] New actions in either workflow are SHA-pinned per `ci-tooling.md`.
