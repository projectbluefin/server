---
name: ci-tooling
description: CI workflow conventions for Bluefin Server. Use when writing or editing .github/workflows/*.yml, debugging a failing build job, or adding a new CI step.
metadata:
  type: reference
  status: stable
  last_updated: "2026-09-30"
  context7-sources:
    - /websites/github_en_actions
    - /websites/cli_github_manual
    - /actions/setup-go
---
# CI Tooling

## When to Use

- Writing a new workflow or job.
- Adding a new action dependency.
- Debugging a CI failure in the build or release job.

## When NOT to Use

- Debugging a BST build failure locally (see `bump-fsdk-version.md`).
- Adding build/deployment logic that should live in the `Justfile` instead of CI.

## Org Conventions

### Action pins — always use SHA, never mutable tags

Every `uses:` line must reference a full commit SHA. Never use `@v2` or `@main`.

```yaml
# correct (see build.yml for the current pinned SHA)
- uses: taiki-e/install-action@<full-commit-sha> # v2

# wrong — mutable tag, supply-chain risk
- uses: taiki-e/install-action@v2
```

Check `.github/workflows/build.yml` (and sibling repos such as
`projectbluefin/dakota` and `projectbluefin/common`) for the current pinned SHA
before adding an action.

### Installing `just` — taiki-e/install-action, not snap/cargo/apt

Pin the tool version too, not only the action SHA. Without `@<version>`,
`install-action` resolves `just@latest` at run time, so the CI contract
(`just validate`, `just test-unit`, the DDI/kernel export recipes) runs against
a binary chosen by an upstream release rather than by a commit in this repo.

```yaml
- uses: taiki-e/install-action@<full-commit-sha> # v2 — see build.yml for the current pin
  with:
    tool: just@1.58.0
```

The version is repeated at each call site — currently `build.yml`,
`unit-tests.yml`, and `track-junctions.yml`. Bumping `just` means changing all
of them in one commit, so CI never runs two versions at once.

Native lifecycle unit tests use SHA-pinned `actions/setup-go` with
`go-version-file: files/server/bootstrap/go.mod` and `cache: false`. The
stdlib-only module has no dependency cache. `just test-unit` uses
`GOTOOLCHAIN=local`; test execution must not silently download another Go
toolchain or depend on the runner's apt Go version.
CI explicitly installs `bubblewrap` and enables unprivileged user namespaces for
the real isolated launcher regressions. The native Go suite runs with `-v` so
individual PASS/SKIP results remain visible; a missing sandbox is not proof of
payload verification.
Vendor-keyring fixtures mount a private `/usr/lib/systemd` before binding the
keyring; never assume the runner already has that file. Rejection tests require
`gpgv` evidence and reject sandbox setup errors, not merely any nonzero exit.
The unit step sets `TMPDIR: ${{ runner.temp }}` so Complete launcher fixtures
back `/etc` and `/var` with runner work storage rather than a nonpersistent
system temporary filesystem. Keep the launcher's production filesystem guard.

### Workflow permissions

`.github/workflows/build.yml` defaults to a read-only token:

```yaml
permissions:
  contents: read
```

The workflow checks out and executes PR-controlled code (the `Justfile` and
build scripts come from the PR head), so no job that runs on `pull_request`
may hold a write token. In `build.yml`, write tokens are granted to exactly
one job:

- `release` — creates the GitHub Release and pushes the OCI artifact; gated to
  `refs/heads/main`. It holds `contents: write` (release),
  `packages: write` (ghcr.io push and attestation referrers), and
  `id-token: write`, `attestations: write` and `artifact-metadata: write`
  for the provenance and SBOM attestations.

Its pull-request rehearsal, `release-dry-run`, keeps the read-only default
and uses no secrets.

Junction ref tracking must never run on `pull_request`. It used to, as a
`track-refs` job gated on `startsWith(github.head_ref, 'renovate/')`, and a
branch name is not an identity. It also pushed its result onto whatever PR
branch happened to be open, so unrelated dependency PRs silently carried
freedesktop-sdk and gnome-build-meta bumps. It now lives in
`track-junctions.yml` on a schedule, opening its own PR on its own branch.

The `build` job (validation, compile, signing) runs with the read-only default
on every event. `changes` adds only `pull-requests: read`, to list a pull
request's files. If a new job needs additional permissions, keep them as
narrow as possible and document why.

### `sudo` scope

Use rootless podman in build jobs wherever possible. Only use `sudo podman` when
the step genuinely requires root (e.g. BST artifact cache access). Do not mix
`sudo podman` and plain `podman` within the same job — pick one based on what the
runner supports and stay consistent.

The `sudo_cmd` Just variable auto-detects at recipe startup:

```just
sudo_cmd := if `podman info >/dev/null 2>&1 && echo 1 || echo 0` == "1" { "" } else { "sudo" }
```

### No PATs; GitHub App tokens for automation that must trigger CI

- Personal Access Tokens (PATs) are banned.
- `repository_dispatch` is not used for build handoff.
- `secrets.GITHUB_TOKEN` is used for release uploads inside `build.yml`.
- Automation that pushes a branch and opens a PR uses the org-wide
  `mergeraptor` GitHub App (`secrets.MERGERAPTOR_APP_ID` /
  `secrets.MERGERAPTOR_PRIVATE_KEY`) via `actions/create-github-app-token`, as
  `projectbluefin/dakota` does. This is not cosmetic: pushes made with
  `secrets.GITHUB_TOKEN` do not dispatch workflow runs, so a PR built that way
  sits at `action_required` with zero jobs and never gets checks.

## Workflow Structure

| Job | Workflow | Trigger | Purpose |
|-----|----------|---------|---------|
| `track-junctions` | `track-junctions.yml` | `schedule` (08:00 UTC), `workflow_dispatch` | Resolves the `freedesktop-sdk.bst` junction ref, syncs `project.conf`'s `installer-version`, and opens/updates its own PR on `auto/track-junctions`. `contents: write` + `pull-requests: write`, never on `pull_request`. |
| `changes` | `build.yml` | `pull_request` (`opened`, `synchronize`, `reopened`, `labeled`), `push/main`, `schedule` (05:30 UTC), `workflow_dispatch` | Decides what the run builds. `release=true` only for a push or dispatch on `main`; it is the one switch that hands out the signing secrets, picks the release version and publishes. `image=true` (full `build` + `boot-test`) for releases, the nightly schedule and dispatches; on a pull request only with the `full-build` label or when it changes `elements/freedesktop-sdk.bst` or `patches/`, and never when `.github/scripts/image-build-needed.py`, checked out from the PR's base revision, finds no changed path that can reach the image set or the boot test (see [Build time and caches](#build-time-and-caches)). `validate=true` for every pull request event except adding an unrelated label. `contents: read` + `pull-requests: read`. |
| `validate` | `build.yml` | `pull_request` | `just validate` with throwaway keys: resolves every shipped element graph and runs the version-invariant checks, in minutes. Read-only token. |
| `build` | `build.yml` | when `changes` says `image=true` | Resolves the element graph, sets `image-version`, and runs the full BuildStream compile of the image set (OS DDI, signed UKIs, netboot ESP, k0s/KubeStellar/kubeadm/OpenZFS/NVIDIA sysext assets), which also writes and signs the combined `SHA256SUMS` inside `oci/bluefin-server-image.bst`. For releases it installs the `BOOT_KEYS_TARBALL` and `SYSUPDATE_SIGNING_KEY` secrets; both are required there. Every other build uses throwaway keys and also exports two higher-versioned sets (`1.<run>.1`, `1.<run>.2`) for the update test. Read-only token. |
| `boot-test` | `build.yml` | after `build` | Runs the Secure Boot QEMU checks on the exported sets (see Core Process step 4). Read-only token. |
| `release` | `build.yml` | `release=true` | Publishes `dist/diskless/` as-is through `scripts/publish-release.sh`: an immutable GitHub Release tagged `v<image-version>` plus an ORAS OCI artifact at `ghcr.io/<owner>/bluefin-server:<ver>,latest` (one layer per file, artifact type `application/vnd.projectbluefin.server.release.v1`), with provenance and SBOM attestations for both (`if: ${{ !failure() && !cancelled() && needs.changes.outputs.release == 'true' }}`). Write permissions listed above. Main runs queue, so a merge that edits `build.yml` can land before an earlier run publishes; GitHub then refuses `GITHUB_TOKEN` a tag at that run's commit (it would need the `workflows` permission). `publish-release.sh taggable` detects this before anything is published and skips that version with a warning; the newer run releases its content. |
| `release-dry-run` | `build.yml` | `pull_request` that builds | Runs the same `scripts/publish-release.sh` commands against the PR's image set: verify, render `gh release create`, and a real `oras push` to a `registry` service container (pinned by digest) that it pulls back. Read-only token, no secrets. |
| `docs` | `docs-checks.yml` | `pull_request`, `push/main` | Runs markdown and skill metadata checks via `docs-checks.py`. Read-only token. |
| `reproducibility` | `reproducibility.yml` | `schedule` (Mondays 09:00 UTC), `workflow_dispatch` | Builds the image set, deletes the final-assembly artifacts, rebuilds them without remote caches and diffs every output except `*.gpg` (see "Reproducible builds" in `ddi-installer-build.md`). Throwaway keys, nothing published. Read-only token. |
| `unit` | `unit-tests.yml` | `pull_request`, `push/main` | Runs pytest and BATS unit test suites. Read-only token. |
| `check`, `propose` | `track-binaries.yml` | `schedule` (08:30 UTC), `workflow_dispatch` | `check` finds the newest patch release in each pinned series of the upstream components pinned by version + sha256 (Kubernetes, cri-tools, containerd, runc, CNI plugins, k0s, each NVIDIA driver flavour inside its branch, ORAS) or by version + git commit (NVIDIA Container Toolkit) with `.github/scripts/track-binaries.py`; `propose` moves each version together with its sha256 pins for every pinned architecture (amd64 and the `arch == "aarch64"` sources), verified against upstream's checksum files and the downloaded assets (a git commit: the GitHub API and `git ls-remote` must agree), and opens or updates one PR per component on `auto/track-binaries/<component>`. Minor bumps stay manual (`kubeadm-sysext.md`, `k0s-sysext.md`); a new NVIDIA branch is a new flavour (`nvidia-sysext.md`). Read-only `GITHUB_TOKEN`; writes use the mergeraptor app token narrowed to `contents` + `pull-requests` (+ `workflows` for ORAS, pinned in `build.yml`). Never on `pull_request`. |

GitHub Actions runs the **complete BuildStream compilation pipeline** using `/mnt`
SSD storage on the runner for podman and BuildStream caches. Release assets are
uploaded to a GitHub Release tagged `v<image-version>` (`YY.MM.<run>` on main).

## Core Process

1. **Renovate tracking:** `renovate.json` is configured with a custom regex
   manager to scan the BuildStream junction (`freedesktop-sdk.bst`) using the
   `git-refs` datasource.
 2. **Auto-resolution:** The scheduled `track-junctions` workflow executes
    `just bst source track` to resolve raw tags to full `git-describe` refs,
    syncs `installer-version` to the tracked FSDK point release, and proposes the
    result as its own pull request against `main`.
 3. **Full Compilation:** Builds the OS DDI, signed UKIs, netboot ESP, and the
    k0s, KubeStellar, kubeadm, OpenZFS and NVIDIA systemd-sysext assets for every push to
    `main`, every night, and on pull requests that carry `full-build` or change
    the FSDK junction or its patches, and signs the combined `SHA256SUMS`
    inside `oci/bluefin-server-image.bst` (gpg sign plus a `gpgv` proof
    against the shipped keyring). Other pull requests run `validate`.
 4. **Boot test:** Downloads the exported image sets and runs, in QEMU with
    Secure Boot OVMF, each as one `scripts/dogfood-diskless.sh --check` or
    `scripts/dogfood-install.sh` or `scripts/dogfood-installer.sh` call. The firmware is Fedora's
    `edk2-ovmf` (Koji URL + SHA-256 in `build.yml`), not Ubuntu's `ovmf`:
    Ubuntu 26.04's OVMF 2025.11 rejects systemd-boot's PK enrollment
    (`Failed to write PK secure boot variable: Security violation`), and
    until this was caught every CI boot ran in setup mode with Secure Boot
    off. `--check` now fails unless the probe reports
    `secureboot=enabled` (or, for tamper runs, the kernel logs
    `Secure boot enabled`). Bump the pin by hand; Renovate does not track it.
    The runner package step explicitly installs `mtools`, which provides `mcopy`
    for selecting the signed installer UKI profile in the ESP. Do not rely on
    hosted runner preinstalls; use `apt-get update` before `apt-get install`
    ([runner customization](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/customize-runners)).
    - diskless netboot, no failed units; `tests/fixtures/nfs/netdb.probe`
      must see `tcp` and `sunrpc` resolve, the local portmapper answer
      `rpcinfo`, and an NFSv3 mount get past the protocol lookup
      (`DOGFOOD_EXPECT`);
    - `DOGFOOD_TAMPER=raw`: a corrupted DDI must be refused by the manifest
      check (`DOWNLOAD INVALID: Checksum of ... did not check out`);
      `DOGFOOD_TAMPER=sums`: the same DDI with `SHA256SUMS` re-hashed to match
      it must be refused by the signature check (`DOWNLOAD INVALID: Signature
      verification failed`). Both only after the image, `SHA256SUMS` and
      `SHA256SUMS.gpg` were served, and nothing may boot;
    - Ignition from the `ignition.config` credential, and UEFI HTTP boot with
      `bluefin-node.ign` served next to the UKI, both with
      `tests/fixtures/ignition/apply-marker.ign`: the probe must see the
      written file and the Ignition-enabled unit active (`DOGFOOD_EXPECT`);
    - releases: diskless boot, `systemd-sysinstall` to disk, boot the disk;
    - every other build (the nightly build of `main`, `full-build` and FSDK
      pull requests, dispatches): the same, then `systemd-sysupdate` A->B to
      `1.<run>.1` and a boot-counted rollback from a corrupted `1.<run>.2`,
      with the ZFS and NVIDIA sysexts merged together
      (`DOGFOOD_SYSEXT=zfs,nvidia`; see
      [ddi-installer-build.md](ddi-installer-build.md), also for why not
      `0.<run>.N`). Releases skip this because their extra sets would be
      release-signed versions nobody publishes; the nightly dev-key build of
      `main` runs it instead.
    - `scripts/dogfood-installer.sh`: the offline USB installer installs
      unattended onto a blank disk, which then boots with and without the
      installer attached.
 5. **Version Derivation:** The release version is set per build with
    `just set-version`: `YY.MM.<run>` for releases, `0.<run>` for every other
    build so it can never sort above a release.
 6. **Automated Publishing:** For pushes to `main` (including Renovate PR
    merges), GitHub Actions publishes `dist/diskless/` as-is: an immutable
    GitHub Release `v<image-version>` and an ORAS OCI artifact
    `ghcr.io/<owner>/bluefin-server:<ver>,latest`. Nodes verify updates
    against the `SHA256SUMS` / `SHA256SUMS.gpg` already in that set. Every
    pull request that builds rehearses this path in `release-dry-run`, so the
    publish code is exercised before it first runs on main. Attestations, the SBOM
    and the verify commands are in
    [`systemd-sysupdate-verification.md`](systemd-sysupdate-verification.md).

## Build time and caches

Measured on run 36499270842 (pull request, cold runner): `Build and export the
image set` took 2 h. BuildStream pulled 239 artifacts and built 85 (about 3.9 h
of build time over 4 cores). The critical path is FSDK's
`components/linux.bst`: 6 min to fetch its source (not in any source cache)
and 1 h 43 min to build. FSDK's caches never hold it for us, because the
`components/linux-module-cert.bst` junction override (our module certificate)
and `patches/freedesktop-sdk/0006-linux-*.patch` change its cache key. The
other ~70 min of parallel build time on that run came from about 40 FSDK
elements (glib-stage1, gobject-introspection, harfbuzz, vala, ...) pulled in
only by FSDK's `components/os-release.bst` in `base/base-stack.bst`, and
patched by `0002`–`0005`; both are gone, which removes 57 elements from the
graph. Go (for ignition) still builds from source. Changing only `image-version`
rebuilds 13 version-stamped elements (os-release to `oci/bluefin-server-image.bst`
and the sysexts), 2 min locally on a warm cache; CI's
per-set cost is estimated at under 10 min.
Every image build also builds the NVIDIA driver sysext (a ~400 MB `.run`
download, about 1 min of module build, signing, and a repack per image
version) and the NVIDIA Container Toolkit (Go); the driver sysext adds about
183 MB to each image set.

- **Docs-only pull requests skip the build.** The `changes` job feeds the PR's
  changed paths (renames under both names) to
  `.github/scripts/image-build-needed.py` from the base revision, so a PR
  cannot edit the classifier to skip its own build; a change to the
  classifier or `build.yml` always builds. It answers `false` only when every
  path is docs, Markdown outside the build inputs, `tests/unit/`,
  `tests/e2e/`, or a workflow or script that does not build the image;
  `tests/unit/test_image_build_needed.py` fails if any tracked build input
  (`elements/`, `files/`, `include/`, `patches/`, `plugins/`, `scripts/`,
  `tests/fixtures/`, `project.conf`, `Justfile`, `build.yml`) would skip. No
  status check is required on `main` today; a skipped job reports as passing,
  so they can be made required without `paths-ignore` leaving them pending.
- **Kernel cache in ghcr.io, key-free by construction.** The `kernel-cache`
  job (releases only) runs `scripts/kernel-cache.sh seed`: with no signing
  secrets and the committed release module certificate
  (`files/release-keys/linux-module-cert.crt`) staged as
  `files/boot-keys/modules/linux-module-cert.crt`, it builds FSDK's
  `components/linux.bst` and `components/go.bst` into an empty BuildStream
  cache and pushes that cache as a zstd tarball (split into 1.9 GB layers) to
  `ghcr.io/<owner>/bluefin-server-bst-cache:kernel-<hash of both cache keys>`,
  unless the tag exists. `build` then runs `kernel-cache.sh restore` into its
  cache before building, and gets the kernel as `cached`; restore reads the
  whole stream (zstd checksums, every tar header) before extracting, so a
  corrupt download leaves the cache untouched instead of half-populated.
  Release builds
  normalize `BOOT_KEYS_TARBALL`'s module certificate to the committed bytes
  after checking it is the same certificate (and stop if not), so the keys
  match. The tarball is public: `seed` refuses if
  `bluefin-server/keys/boot-keys.bst` is anywhere in the graph it builds, and
  the job holds no secret but `GITHUB_TOKEN`. A content grep is no guard
  here: FSDK sources (Go's TLS test data and others) carry 307 PEM private
  keys. Both cache steps are `continue-on-error`, so a failed seed or restore
  only costs time. Measured in the lab: the seed build takes 44 min on 16+
  CPUs, fills 15 GB, and packs to 5.0 GB in under a minute; a restored cache
  reports the element `cached` where an empty one reports `fetch needed`.
  Only a kernel or Go change (FSDK bump, patch `0006`, module certificate)
  reseeds.
- **No other cache push.** `bluefin-server/keys/boot-keys.bst` imports
  `files/boot-keys/`, which on `main` holds the Secure Boot, module-signing
  and sysupdate private keys, and the image, UKIs, `kernel-modules.bst`,
  `efi-keys.bst`, `os-sd-boot-signed.bst`, `openzfs-signed.bst` and the
  `nvidia-open-*-signed.bst` elements
  build-depend on it, so a release build's own cache must never be saved or
  pushed anywhere a pull request can read.
- **Most pull requests do not build the image.** The full build costs about
  1.5 h, most of it FSDK's kernel, so a pull request builds only with the
  `full-build` label or when it changes `elements/freedesktop-sdk.bst` or
  `patches/` (an untested FSDK bump would otherwise merge unbuilt); the rest
  run `validate`. A regression outside those paths shows up in the next
  `main` build or the nightly build, both of which block nothing but the
  release that contains it. When a pull request does build, it still builds
  the kernel: `just gen-dev-keys` makes a new module certificate on every
  run, so the PR kernel's cache key never matches anything cached.
- **No `actions/cache`.** A full build's cache holds `boot-keys.bst`, and
  pull requests can restore caches saved on `main`; the key-free kernel cache
  is 5 GB, half the 10 GB repository quota, so it lives in ghcr.io instead.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It's just a minor version tag, supply-chain risk is low." | One compromised tag push owns every repo using it. Pin to SHA. |
| "I'll check what SHA other repos use later." | Check now — it's one `gh api` call and takes a few seconds. |
| "`tool: just` always installs a working version." | It installs whatever is latest that day. A `just` release can change recipe parsing or `--fmt` output and break CI with no commit in this repo. |

## Red Flags

- Any `uses:` line with a mutable ref (`@v2`, `@main`, `@latest`).
- An `install-action` step whose `tool:` has no `@<version>` — the pin is half
  done, since the action is fixed but the binary it installs is not.
- `sudo podman` in one step and plain `podman` in another step doing the same
  operation.
- A new action not present in any sibling repo — check upstream first.

## Verification

- [ ] Every `uses:` line has a full 40-character SHA and a `# vX` comment.
- [ ] Every `install-action` `tool:` names an explicit version (`just@1.58.0`).
- [ ] `just validate` passes after workflow changes.
- [ ] `just test-unit` runs `tests/unit`, `files/server/manifests/tests`, the
      native lifecycle Go suite, and Bats; the CI unit job uses this same recipe.
- [ ] A new directory the build or boot test reads is listed in
      `BUILD_PREFIXES` in `.github/scripts/image-build-needed.py`.
- [ ] No new mutable action refs introduced.
- [ ] Release signing happens in `oci/bluefin-server-image.bst`; there is no
      separate CI signing step, and the release job publishes `dist/diskless/`
      as-is (GitHub Release + OCI artifact).
- [ ] Publish logic lives in `scripts/publish-release.sh`, not inline in the
      workflow; `tests/unit/test_release_workflow.py` keeps `release` and
      `release-dry-run` on the same commands and the same `setup-oras` pin.
- [ ] The signing secret names (`BOOT_KEYS_TARBALL`, `SYSUPDATE_SIGNING_KEY`)
      match the ones documented in
      `docs/skills/systemd-sysupdate-verification.md`.

## See also

- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) — release signing and sysupdate verification.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
