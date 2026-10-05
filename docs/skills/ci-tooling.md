---
name: ci-tooling
description: CI workflow conventions for Bluefin Server. Use when writing or editing .github/workflows/*.yml, debugging a failing build job, or adding a new CI step.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-04"
  context7-sources:
    - /websites/github_en_actions
    - /websites/cli_github_manual
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

The version is repeated at each call site — currently six steps in four
workflows: `build.yml` (three jobs), `reproducibility.yml`, `unit-tests.yml`
and `track-junctions.yml`. Bumping `just` means changing all of them in one
commit, so CI never runs two versions at once;
`tests/unit/test_ci_tool_pins.py` fails if they drift.

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
freedesktop-sdk junction bumps. It now lives in
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
- `github.token` (the job's `GITHUB_TOKEN`) is used for release uploads
  inside `build.yml`.
- Automation that pushes a branch and opens a PR uses the org-wide
  `mergeraptor` GitHub App (`secrets.MERGERAPTOR_APP_ID` /
  `secrets.MERGERAPTOR_PRIVATE_KEY`) via `actions/create-github-app-token`, as
  `projectbluefin/dakota` does. This is not cosmetic: pushes made with
  `secrets.GITHUB_TOKEN` do not dispatch workflow runs, so a PR built that way
  sits at `action_required` with zero jobs and never gets checks. The jobs
  mint that token only right before the push and PR step, after every step
  that runs repository or upstream code, narrowed with
  `permission-contents: write` and `permission-pull-requests: write`, and
  push with a one-off `http.<server>/.extraheader`; the checkout keeps no
  credentials.
- Every `actions/checkout` sets `persist-credentials: false`; no job pushes
  with the checkout's token.

### Environments and secrets

A `pull_request` from a branch of this repository, or a push to any branch,
runs that branch's copy of the workflow, and repository and organization
secrets reach it. So every secret beyond `GITHUB_TOKEN` lives in an
environment whose deployment branch policy allows only `main` (no required
reviewers, so releases are not held up). A job from any other ref that names
one of these environments is refused before its first step.

| Environment | Secrets | Jobs |
|---|---|---|
| `release` | `BOOT_KEYS_TARBALL`, `SYSUPDATE_SIGNING_KEY` | `build`, only when `changes` says `release=true` |
| `bst-cache` | `CASD_CLIENT_KEY` (`CASD_CLIENT_CERT` is a repository variable) | `kernel-cache`, `kernel-cache-dev` (releases only) |
| `trackers` | `MERGERAPTOR_APP_ID`, `MERGERAPTOR_PRIVATE_KEY` | `track-junctions`, `track-binaries`' `propose` |

`build` serves releases and every other build, so it names the environment
with `${{ needs.changes.outputs.release == 'true' && 'release' || '' }}`: an
empty name means no environment, which is how pull requests, the nightly
build and branch dispatches run. Inside the job, the `&& secrets.X || ''`
gates stay as a second layer. `release` publishes with `github.token` alone
and names no environment. `tests/unit/test_release_workflow.py` fails if a
job outside this table reads a secret or a listed job loses its environment.

Moving a value is an admin step (no workflow change). Environment secrets
override repository and organization secrets of the same name, so set the
environment copy first, then remove the old one:

```bash
gh secret set BOOT_KEYS_TARBALL --repo projectbluefin/server --env release < boot-keys.tar.gz.b64
gh secret set SYSUPDATE_SIGNING_KEY --repo projectbluefin/server --env release < sysupdate-signing.asc
gh secret set CASD_CLIENT_KEY --repo projectbluefin/server --env bst-cache < client.key
gh secret set MERGERAPTOR_APP_ID --repo projectbluefin/server --env trackers --body "<app id>"
gh secret set MERGERAPTOR_PRIVATE_KEY --repo projectbluefin/server --env trackers < mergeraptor.pem
gh secret delete BOOT_KEYS_TARBALL --repo projectbluefin/server   # and the other repository copies
```

The mergeraptor secrets are organization secrets that other repositories
use: remove only this repository from their repository access.

## Workflow Structure

| Job | Workflow | Trigger | Purpose |
|-----|----------|---------|---------|
| `track-junctions` | `track-junctions.yml` | `schedule` (08:00 UTC), `workflow_dispatch` | Resolves the `freedesktop-sdk.bst` junction ref, syncs `project.conf`'s `installer-version`, and opens/updates its own PR on `auto/track-junctions`. Read-only `GITHUB_TOKEN`; the push and the PR use the mergeraptor app token (`trackers` environment), minted after `just bst source track` and narrowed to `contents` + `pull-requests`. Never on `pull_request`. |
| `changes` | `build.yml` | `pull_request` (`opened`, `synchronize`, `reopened`, `labeled`), `push/main`, `schedule` (05:30 UTC), `workflow_dispatch` | Decides what the run builds. `release=true` only for a push or dispatch on `main`; it is the one switch that hands out the signing secrets, picks the release version and publishes. `image=true` (full `build` + `boot-test`) for releases, the nightly schedule and dispatches; on a pull request only with the `full-build` label or when it changes `elements/freedesktop-sdk.bst` or `patches/`, and never when `.github/scripts/image-build-needed.py`, checked out from the PR's base revision (the job itself comes from the PR head; see [Build time and caches](#build-time-and-caches)), finds no changed path that can reach the image set or the boot test (see [Build time and caches](#build-time-and-caches)). `validate=true` for every pull request event except adding an unrelated label. `contents: read` + `pull-requests: read`. |
| `validate` | `build.yml` | `pull_request` | `just validate` with throwaway keys: resolves every shipped element graph and runs the version-invariant checks, in minutes. Read-only token. |
| `build` | `build.yml` | when `changes` says `image=true` | Resolves the element graph, sets `image-version`, and runs the full BuildStream compile of the image set (OS DDI, signed UKIs, netboot ESP, k0s/KubeStellar/kubeadm/OpenZFS/NVIDIA sysext assets), which also writes and signs the combined `SHA256SUMS` inside `oci/bluefin-server-image.bst`. For releases it runs in the `release` environment and installs its `BOOT_KEYS_TARBALL` and `SYSUPDATE_SIGNING_KEY` secrets; both are required there. Other builds use no environment. Every other build uses throwaway keys and also exports two higher-versioned sets (`1.<run>.1`, `1.<run>.2`) for the update test. Read-only token. |
| `boot-test` | `build.yml` | after `build` | Runs the Secure Boot QEMU checks on the exported sets (see Core Process step 4), with the harness checked out at the commit `build` built. Read-only token. |
| `release` | `build.yml` | `release=true` | Publishes `dist/diskless/` as-is through `scripts/publish-release.sh`: an immutable GitHub Release tagged `v<image-version>` plus an ORAS OCI artifact at `ghcr.io/<owner>/bluefin-server:<ver>,latest` (one layer per file, artifact type `application/vnd.projectbluefin.server.release.v1`), with provenance and SBOM attestations for both. It runs only when `build` and `boot-test` succeeded (`!cancelled()` plus each job's result, so a failed `kernel-cache` does not hold it back), and marks the set latest (GitHub "Latest", ghcr `latest`) only when no newer version is published (see "Publishing" in `systemd-sysupdate-verification.md`). Write permissions listed above. Main runs queue, so a merge that edits `build.yml` can land before an earlier run publishes; GitHub then refuses `GITHUB_TOKEN` a tag at that run's commit (it would need the `workflows` permission). `publish-release.sh taggable` detects this before anything is published and skips that version with a warning; the newer run releases its content. |
| `release-dry-run` | `build.yml` | `pull_request` that builds | Runs the same `scripts/publish-release.sh` commands against the PR's image set: verify, render `gh release create`, and a real `oras push` to a `registry` service container (pinned by digest) that it pulls back. Read-only token, no secrets. |
| `docs` | `docs-checks.yml` | `pull_request`, `push/main` | Runs markdown and skill metadata checks via `docs-checks.py`. Read-only token. |
| `reproducibility` | `reproducibility.yml` | `schedule` (Mondays 09:00 UTC), `workflow_dispatch` | Builds the image set, deletes the final-assembly artifacts, rebuilds them without remote caches and diffs every output except `*.gpg` (see "Reproducible builds" in `ddi-installer-build.md`). Throwaway keys, nothing published. Read-only token. |
| `unit` | `unit-tests.yml` | `pull_request`, `push/main` | Runs pytest and BATS unit test suites. Read-only token. |
| `check`, `propose` | `track-binaries.yml` | `schedule` (08:30 UTC), `workflow_dispatch` | `check` finds the newest patch release in each pinned series of the upstream components pinned by version + sha256 (Kubernetes, cri-tools, containerd, runc, CNI plugins, k0s, each NVIDIA driver flavour inside its branch, ORAS) or by version + git commit (NVIDIA Container Toolkit), and the newest dated snapshot of the IANA registries behind `/etc/protocols` and `/etc/services` (`iana-etc`, no series), with `.github/scripts/track-binaries.py`; `propose` moves each version together with its sha256 pins for every pinned architecture (amd64 and the `arch == "aarch64"` sources), verified against upstream's checksum files and the downloaded assets (a git commit: the GitHub API and `git ls-remote` must agree), and opens or updates one PR per component on `auto/track-binaries/<component>`. Minor bumps stay manual (`kubeadm-sysext.md`, `k0s-sysext.md`); a new NVIDIA branch is a new flavour (`nvidia-sysext.md`). Read-only `GITHUB_TOKEN`; writes use the mergeraptor app token (`trackers` environment, `propose` only), minted after the apply step and narrowed to `contents` + `pull-requests` (+ `workflows` for ORAS, pinned in `build.yml`). Never on `pull_request`. |

Both trackers commit, push and open or update their pull request through
`.github/scripts/propose-pr.sh`. It pushes nothing when the paths already
match `main`, or when an open PR's branch already holds the same content, so
a daily run neither force-pushes an identical commit nor restarts that PR's
build; `track-binaries` also passes `--skip-closed-title`, so a release
whose PR was closed is not proposed again.

GitHub Actions runs the **complete BuildStream compilation pipeline** using `/mnt`
SSD storage on the runner for podman and BuildStream caches
(`scripts/ci-runner-disk.sh`, called by every job that builds). Release assets are
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
     installer attached. Outside releases it then gets `1.<run>.1`
     (`dist/diskless-next`) the way a PC installed from the stick does:
     an unreachable and a foreign-signed source must fail
     `systemd-sysupdate.service` and show on the login banner, the update
     must stage, boot and be blessed (see "Update health on the node" in
     [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)).
     Two more runs install onto disks that are not empty (#359): again over
     a Bluefin install (`DOGFOOD_TARGET=prior-install`) and over another
     OS's GPT disk (`DOGFOOD_TARGET=foreign-gpt`).
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

The canonical build-time figures; other files link here instead of
restating them:

- **Full image build:** the `build` job on `main` takes a median of about
  50 min and a 90th percentile of about 2 h (56 successful runs,
  2026-09-24 to 2026-10-04). The slow runs are the ones that compile the
  kernel.
- **FSDK's kernel when no cache holds it:** 1 h 43 min to build, plus 6 min
  to fetch its source; it is the critical path of a cold build.

Where a cold build's time goes (run 36499270842, pull request, cold runner):
BuildStream pulled 239 artifacts and built 85 (about 3.9 h of build time over
4 cores), with FSDK's `components/linux.bst` on the critical path. FSDK's
caches never hold it for us, because the
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
  `.github/scripts/image-build-needed.py` from the base revision, so editing
  the classifier does not skip the PR's own build; a change to the
  classifier or `build.yml` always builds. The `changes` job itself runs
  from the PR head's `build.yml`, which a PR can edit to skip anything: the
  control for that is reviewing workflow changes. It answers `false` only when every
  path is docs, Markdown outside the build inputs, `tests/unit/`,
  `tests/e2e/`, or a workflow or script that does not build the image;
  `tests/unit/test_image_build_needed.py` fails if any tracked build input
  (`elements/`, `files/`, `include/`, `patches/`, `plugins/`, `scripts/`,
  `tests/fixtures/`, `project.conf`, `Justfile`, `build.yml`) would skip. No
  status check is required on `main` today; a skipped job reports as passing,
  so they can be made required without `paths-ignore` leaving them pending.
- **Kernel cache in the project CAS, key-free by construction.** Two jobs,
  on releases only, run `scripts/kernel-cache.sh seed`, one per module
  certificate the kernel can trust (it is part of the kernel's cache key):
  - `kernel-cache` runs `seed release` with the committed release certificate
    (`files/release-keys/linux-module-cert.crt`); `build` waits for it.
  - `kernel-cache-dev` runs `seed dev` with the public INSECURE dev
    certificate (`files/dev-keys/INSECURE-dev-module-key.crt`) that
    `just gen-dev-keys` uses for every non-release build. No job waits for
    it, so it never delays a release.

  With no signing secrets and that one certificate staged as the only file of
  `files/boot-keys/modules/` (`seed` refuses anything else there: that
  directory's import is pushed with the kernel), each builds FSDK's
  `components/linux.bst` and `components/go.bst` with a BuildStream config
  that pushes artifacts and sources to `cache.projectbluefin.io:11002`,
  unless `bst artifact show` reports both `available` on a remote. The push
  endpoint takes mTLS: the client certificate is the repository variable
  `CASD_CLIENT_CERT` and its key the `bst-cache` environment secret
  `CASD_CLIENT_KEY`, given to that step only and written to a gitignored `.casd.*/` directory that the script
  removes on exit. The CAS trusts that certificate in its list of client
  certificates; rotating it means replacing it there and in both settings.
  Every build then pulls the kernel anonymously through the
  `cache.projectbluefin.io:11001` remote configured in `project.conf` and
  injected into the junction's `project.conf` via
  `patches/freedesktop-sdk/0001-project.conf-Add-GNOME-CAS-servers.patch`. Release builds
  normalize `BOOT_KEYS_TARBALL`'s module certificate to the committed bytes
  after checking it is the same certificate (and stop if not), so the keys
  match, and run `scripts/check-release-keys.sh`, which fails the build if
  the module certificate or key is the dev pair; `seed release` runs it too.
  The CAS is publicly readable: `seed` refuses if
  `bluefin-server/keys/boot-keys.bst` is anywhere in the graph it builds,
  and the job holds no signing secret. A content grep is no guard here: FSDK
  sources (Go's TLS test data and others) carry 307 PEM private keys. The
  seed step is `continue-on-error`, so a failed seed only costs time; the
  next step then posts a warning and a step summary line.
  Measured in the lab: the seed build takes 44 min on 16+ CPUs and fills
  15 GB. Only a kernel or Go change (FSDK bump, a kernel config patch such as
  `0006` or `0007`, module certificate) reseeds.
- **No other cache push.** `bluefin-server/keys/boot-keys.bst` imports
  `files/boot-keys/`, which on `main` holds the Secure Boot, module-signing
  and sysupdate private keys, and the image, UKIs, `kernel-modules.bst`,
  `efi-keys.bst`, `os-sd-boot-signed.bst`, `openzfs-signed.bst` and the
  `nvidia-open-*-signed.bst` elements
  build-depend on it, so a release build's own cache must never be saved or
  pushed anywhere a pull request can read.
- **Most pull requests do not build the image.** The full build costs up to
  2 h (figures above), most of it FSDK's kernel, so a pull request builds only with the
  `full-build` label or when it changes `elements/freedesktop-sdk.bst` or
  `patches/` (an untested FSDK bump would otherwise merge unbuilt); the rest
  run `validate`. A regression outside those paths shows up in the next
  `main` build or the nightly build, both of which block nothing but the
  release that contains it. When a pull request or the nightly build does
  build, it pulls the kernel that `kernel-cache-dev` seeded: `just
  gen-dev-keys` always stages the same public dev module certificate, so
  the dev kernel's cache key is the same on every run. It compiles the
  kernel (1 h 43 min) only until the next release after a kernel change
  seeds it.
- **No `actions/cache`.** A full build's cache holds `boot-keys.bst`, and
  pull requests can restore caches saved on `main`; the key-free kernel
  cache lives in the project CAS instead.

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
- [ ] A job that reads a secret names its main-only environment
      ([Environments and secrets](#environments-and-secrets)).
- [ ] Every `actions/checkout` sets `persist-credentials: false`.

## See also

- [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md) — release signing and sysupdate verification.
- [CONTEXT.md](../../CONTEXT.md) — canonical project domain glossary.
