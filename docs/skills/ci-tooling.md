---
name: ci-tooling
description: CI workflow conventions for Bluefin Server. Use when writing or editing .github/workflows/*.yml, debugging a failing build job, adding a new CI step, or finding out which automation set a label and what reads it.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-17"
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
## Org Conventions and Workflow Structure

Org-wide conventions — action SHA pins, tool and Python pins, workflow
linting, permissions, `sudo` scope, GitHub App tokens, environments and
secrets — and the per-job workflow table live in
[ci-conventions.md](ci-conventions.md).
## Labels

Prow (`prow.yml`, acting as `github-actions[bot]`) writes its built-in labels and
those of the org config `projectbluefin/.project/prow.yaml`; the hive
(`hivecommons-hive[bot]`) writes its own ([reference](https://github.com/hivecommons/hive/blob/v5/src/docs/labels-and-control-signals.md)).
**Bold** labels gate a build or a merge.

| Label (family) | Set by | Read by / effect | How a human changes it |
|---|---|---|---|
| **`full-build`** | people | `build.yml` `changes`: `image=true` when a changed path can reach the image, so `build`, `boot-test`, `image-check` and `release-dry-run` run on this and every later push | add it (starts the build); remove it to stop building later pushes |
| **`lgtm`** | Prow `/lgtm` from an `OWNERS` entry other than the author, or a person adding it; bound to the head by the `prow/lgtm` status, dropped on new commits | Prow merge gate | `/lgtm`, `/lgtm cancel` |
| **`approved`** | Prow's approve plugin: `/approve` from an `OWNERS` approver, and by itself when the author is one | Prow merge gate: with `OWNERS` files it needs `lgtm` and `approved` | `/approve`, `/approve cancel` |
| **`hold`** | Prow `/hold`; the hive (level gate on its agent PRs, self-authorization, reporter trust, holdguard) | Prow does not merge; the hive holds any item with `hold` in a label | `/hold cancel` (any commenter) or remove it: lifts both at once; holdguard re-adds it if the head moved while held |
| **`sentinel-alert`** | the hive's sentinel (diff heuristics, with a "Sentinel alert" comment) | the hive will not approve, lgtm or auto-merge the PR (`stage/085-needs-decision`); Prow ignores it | remove after review; the hive re-adds it only on new commits |
| **`needs-human`** | the hive (fix budget spent, a workflow change), people | the hive stops fixing and auto-merging the PR; an issue leaves the agent queue; Prow ignores it | remove it once handled |
| `role/*`, `author/*`, `dco`, `no-dco` | the hive | `role/trusted` may auto-merge, the other tiers need a maintainer's `/lgtm` `/approve`; `author/human`, `clanker`, `hive`: who wrote the PR; `author/trusted`, `contributor`, `newcomer`, `untrusted`: the retired spelling of `role/*`; `no-dco`: a commit lacks `Signed-off-by:` | trust: the hive's registry; DCO: `git rebase --signoff` |
| `stage/*` | the hive, one per item, recomputed every cycle | pipeline state; `085`: a person owes a decision; `090-ready-for-human-merge`: only a maintainer's `/lgtm` `/approve` is missing | act on the cause, not the label |
| `agent/*`, `hive/*`, `from-review`, `quality`, `security`, `testing` | the hive | provenance and hive routing | leave them |
| `approved-direction` | the hive on `/hive approve` or `/hive decision <text>`; people | a hive-filed issue is accepted, so a PR for it is not held | `/hive approve` on the issue |
| `kind/*`, `area/*`, `triage/accepted`, `priority/*`, `blocked`, `needs-kind`, `needs-triage`, `ok-to-test`, `help wanted`, `good first issue` | Prow commands (`/triage`, `/priority`, `/label` only for the maintainers roster); `needs-*` on issues without `kind/*` or `triage/*` | classification and hive ranking; `ok-to-test` approves a non-member PR's held Actions runs, now and on later pushes; the `area/*` values are the org's desktop areas | the command or its `/remove-` form |
| `chore/deps`, `automerge` | Renovate, as the mergeraptor app (not from `renovate.json`) | nothing in this repository | Renovate's configuration |

- `approved` from `github-actions[bot]` as a PR opens is Prow counting the
  author's `OWNERS` entry (`require_self_approval` is off), not a second person.
- Prow's gate reads only `lgtm`, `approved`, `hold`, `needs-rebase` and
  `do-not-merge/*`: it merges past `sentinel-alert` and `needs-human`.
- A PR not ready for review gets no reviewers or merge from Prow or the hive
  (`gh pr ready N`). GitHub logs each conversion as a `convert_to_draft`
  timeline event with its actor; with none, the PR was opened that way.
- Verify a label you add with `gh pr view N --json labels`: one
  `gh pr edit --add-label` left no `labeled` event (#490, #491). Add labels
  in their own `gh pr edit` call.

## Core Process

1. **Renovate tracking:** a `renovate.json` regex manager follows the
   `# renovate:` annotation on `elements/freedesktop-sdk.bst` (`git-refs`).
2. **Auto-resolution:** the scheduled `track-junctions` job resolves the
   junction ref and proposes it as its own pull request (see
   [bump-fsdk-version.md](bump-fsdk-version.md)).
3. **Full Compilation:** Builds the OS DDI, signed UKIs, netboot ESP, and the
   k0s, KubeStellar, kubeadm, OpenZFS and NVIDIA systemd-sysext assets for every push to
   `main`, every night, every merge group that can change the image set, and
   on pull requests that carry `full-build` or change the FSDK junction or its
   patches, and signs the combined `SHA256SUMS`
   inside `oci/bluefin-server-image.bst` (gpg sign plus a `gpgv` proof
   against the shipped keyring). Other pull requests run `validate`. Every
   job that builds keeps the podman and BuildStream caches on the runner's
   `/mnt` SSD (`scripts/ci-runner-disk.sh`).
4. **Boot test:** Runs the exported sets in Secure Boot QEMU via
   `scripts/ci/boot-test.sh` (`--list` prints the scenarios); each bucket stops at its first failure.
   Fedora's `edk2-ovmf` is pinned by Koji URL + SHA-256 in `scripts/ci/install-qemu-ovmf.sh`:
   Ubuntu 26.04's OVMF 2025.11 rejects PK enrollment and boots with Secure Boot off
   ([details](ddi-installer-build.md)). Bump by hand: Renovate cannot update the SHA-256.
   - diskless netboot, no failed units; `tests/fixtures/nfs/netdb.probe`
     must resolve `tcp` and `sunrpc`, reach the local portmapper (`rpcinfo`)
     and get an NFSv3 mount past the protocol lookup (`DOGFOOD_EXPECT`);
   - `DOGFOOD_TAMPER=raw` and `=sums`: the pull must refuse a corrupted DDI
     (checksum) and that DDI with `SHA256SUMS` re-hashed to match it
     (signature), and nothing may boot;
   - Ignition from the `ignition.config` credential and from
     `bluefin-node.ign` over UEFI HTTP boot, both with
     `tests/fixtures/ignition/apply-marker.ign` (`DOGFOOD_EXPECT`); outside
     releases also signed with the Ignition config key (applied), with the
     image signing key or over other bytes (refused), and unsigned on the
     `1.<run>.1` set, built with `ignition_allow_unsigned` off (refused;
     see booty-integration.md);
   - releases: diskless boot, `systemd-sysinstall` to disk, boot the disk;
   - every other build (the nightly build of `main`, `full-build` and FSDK
     pull requests, dispatches): the same, then `systemd-sysupdate` A->B to
     `1.<run>.1` and a boot-counted rollback from a corrupted `1.<run>.2`,
     with the ZFS and NVIDIA sysexts merged (`DOGFOOD_SYSEXT=zfs,nvidia`;
     versions: [ddi-installer-build.md](ddi-installer-build.md)). Releases
     skip it: their extra sets would be release-signed versions nobody
     publishes.
   - `scripts/dogfood-installer.sh`: offline unattended install onto a blank disk, then boot
     with and without the stick. Outside releases, update to `1.<run>.1`: unreachable and
     foreign-signed sources must fail `systemd-sysupdate.service` and appear on the login banner;
     the update must stage, boot and be blessed (see "Update health on the node" in
     [sysupdate-operations.md](sysupdate-operations.md)). Two more runs install
     over Bluefin and another OS's GPT disk (`DOGFOOD_TARGET=prior-install`, `foreign-gpt`; #359).
   - The `installer` bucket always runs the attended install with `DOGFOOD_CONSOLE_NOISE=1`,
     then `DOGFOOD_CONSOLE_FAILURE=kernel` in separate disposable state (#454). The harness checks
     fresh foreground state, keyboard input, journal-only noise and disk boot/login on success;
     failure must retain the error and journal, without success handling, reboot/halt or partitions.
     Synthetic noise does not establish physical Bluetooth coverage (#453). On success or failure,
     `boot-test-logs-installer` retains serial journals, screen snapshots and console proof, plus
     `installer-artifact-identity.txt`: the source commit and pre-boot SHA-256 of the installer,
     manifest and signature. Partial logs survive regressions; disks and credentials stay excluded.
5. **Version Derivation:** The release version is set per build with
   `just set-version`: `YY.MM.<run>` for releases, `0.<run>` for every other
   build so it can never sort above a release.
6. **Automated Publishing:** every push to `main` (Renovate merges included)
   publishes `dist/diskless/` as-is (the `release` job; nodes verify updates
   against that set's own `SHA256SUMS` / `SHA256SUMS.gpg`), and
   `release-dry-run` rehearses it on every pull request that builds.
   Attestations, the SBOM and the verify commands are in
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
- **Boot test:** serially, the 15 pull-request scenarios took about 30 min
  (runs 39077147402, 39059748396), the 11 release ones 13 min. Its buckets:
  `diskless` (9 min), `install` (A/B update and rollback, 10 min, the long
  pole), `installer` (5 min), `installer-disks` (4 min), each plus 1-2.5 min
  of setup.

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
  `tests/fixtures/`, `project.conf`, `Justfile`, `build.yml`) would skip.
  A skipped job reports as passing, so its required check does not hold it.
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
  `efi-keys.bst`, `os-sd-boot-signed.bst`, `shim.bst`, `openzfs-signed.bst`
  and the `nvidia-open-*-signed.bst` elements
  build-depend on it, so a release build's own cache must never be saved or
  pushed anywhere a pull request can read.
- **Most pull requests build the image only in the merge queue.** The full
  build costs up to 2 h (figures above), most of it FSDK's kernel, so a pull
  request builds before the queue only with the `full-build` label or when it
  changes `elements/freedesktop-sdk.bst` or `patches/`; the rest run
  `validate`, and the merge queue builds and boot-tests every merge group
  that can change the image set before it reaches `main`. When a pull
  request, a merge group or the nightly build does build, it pulls the kernel that `kernel-cache-dev` seeded: `just
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
- A `paths:` filter on a workflow meant to be a required check: it never
  reports on the pull requests it skips, so they stay pending.
- `pip install <package>` in a workflow instead of the pinned requirements file.
- `sudo podman` in one step and plain `podman` in another step doing the same
  operation.
- A new action not present in any sibling repo — check upstream first.

## Verification

- [ ] Every `uses:` line has a full 40-character SHA and a `# vX` comment.
- [ ] Every `install-action` `tool:` names an explicit version (`just@<version>`).
- [ ] actionlint and zizmor (see [Workflow linting](ci-conventions.md)) report
      nothing.
- [ ] `just validate` passes after workflow changes.
- [ ] A new directory the build or boot test reads is listed in
      `BUILD_PREFIXES` in `.github/scripts/image-build-needed.py`.
- [ ] A new boot test scenario goes in a bucket of `scripts/ci/boot-test.sh`;
      a new host tool in `scripts/ci/dogfood-preflight.sh` and its package in
      `scripts/ci/install-qemu-ovmf.sh`.
- [ ] No new mutable action refs introduced.
- [ ] Release signing happens in `oci/bluefin-server-image.bst`; there is no
      separate CI signing step, and the release job publishes `dist/diskless/`
      as-is (GitHub Release + OCI artifact).
- [ ] Publish logic lives in `scripts/publish-release.sh`, not inline in the
      workflow; `tests/unit/test_release_workflow.py` keeps `release` and
      `release-dry-run` on the same commands and the same `setup-oras` pin.
- [ ] The signing secret names (`BOOT_KEYS_TARBALL`, `SYSUPDATE_SIGNING_KEY`)
      match `docs/skills/sysupdate-operations.md`.
- [ ] A job that reads a secret names its main-only environment
      ([Environments and secrets](ci-conventions.md)).
- [ ] Every `actions/checkout` sets `persist-credentials: false`.
