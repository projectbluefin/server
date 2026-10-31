---
name: ci-conventions
description: Org-wide CI conventions and the workflow job table for Bluefin Server. Load when adding or editing .github/workflows/*.yml — action SHA pins, tool and Python pins, workflow linting, permissions, sudo scope, GitHub App tokens, environments and secrets.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-30"
  context7-sources:
    - /websites/github_en_actions
    - /websites/cli_github_manual
---
# CI conventions and workflow structure

CI process, labels, build times and caches live in
[ci-tooling.md](ci-tooling.md). This file is the org-wide conventions and the
per-job table.
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
    tool: just@<version> # the version every other call site uses
```

The version is repeated at each call site. A Renovate regex manager
(`renovate.json`) matches every `tool: just@` in the workflows and bumps them
in one PR, so CI never runs two versions at once;
`tests/unit/test_ci_tool_pins.py` fails if they drift and
`tests/unit/test_ci_workflows.py` if a call site falls outside the Renovate
manager.

### Python packages and other pins

Workflows install Python packages with
`pip install -r .github/requirements-ci.txt` only, never a bare
`pip install <name>`. The file pins the whole resolved set with `==`, and
Renovate's `pip_requirements` manager proposes the bumps.

The Justfile's `bst2_image` is tagged with the freedesktop-sdk-docker-images
commit it was built from. The docker datasource cannot order those tags, so a
Renovate `git-refs` manager follows that repository's default branch and moves
the tag (a tag, not a digest pin). A failed upstream build leaves it unpublished
and no CI job pulls it, so a package rule keeps these bumps from automerging.

### Python lint

`just lint-python` runs ruff on every Python file (`ruff.toml`: E, F, W, I, UP,
B; disabled rules are explained) and mypy on annotated functions in `scripts/`
and `.github/scripts/` (`mypy.ini`); the `unit` job runs it before tests. The
`pyproject.toml`'s `requires-python` and `.python-version` set 3.14; ruff's
`target-version` matches the runners' system Python, the oldest CI runtime, not
`setup-python`; raise it only when every caller supports it. Lint locally with
`python3 -m pip install -r .github/requirements-ci.txt` in a virtualenv, then
`just lint-python`; `python3 -m ruff check --fix` applies safe fixes.

The pytest half of `just test-unit` runs in parallel (`-n auto`, pytest-xdist)
and measures coverage of the repo's Python (`.coveragerc`: `scripts/`,
`.github/scripts/`, `files/`) into `term-missing:skip-covered`; the `unit`
job appends the same report as markdown to the step summary. `fail_under` in `.coveragerc` is a ratchet (the measured total, rounded down): raise it as coverage grows, never lower it to pass.
importlib-by-path loads are measured, and so are `python3` subprocesses (`patch = subprocess`) unless a test hands them a fresh `env=`.
`pytest.ini` registers two markers: `-m "not slow"` skips the slow tests; `root` tests (real ownership changes, privilege drops) skip unprivileged, and the `unit` job's last step runs them with `sudo ... pytest -m root`, where in CI they fail if not root (`tests/unit/conftest.py`).

### Workflow linting

`lint-actions.yml` runs actionlint and zizmor on every pull request and push
to `main`, each from a container image pinned by digest (`docker://` steps
that Renovate's github-actions manager bumps). `.github/actionlint.yaml`
declares hosted runner labels newer than actionlint's built-in list
(`ubuntu-26.04`). Fix zizmor findings rather than silencing them; when one is
accepted, ignore that rule for that location in `.github/zizmor.yml` with the
reason next to it, never a whole audit. Locally:

```bash
podman run --rm -v "$PWD":/repo:Z -w /repo docker.io/rhysd/actionlint:latest -no-color -oneline
podman run --rm -v "$PWD":/repo:Z -w /repo ghcr.io/zizmorcore/zizmor:latest --offline .
```

### Workflow permissions

`.github/workflows/build.yml` defaults to a read-only token:

```yaml
permissions:
  contents: read
```

The workflow checks out and executes PR-controlled code (the `Justfile` and
build scripts come from the PR head), so no job that runs on `pull_request`
may hold a write token. In `build.yml`, write tokens to the repository's
contents and packages are granted to exactly one job:

- `release` — creates the GitHub Release and pushes the OCI artifact; gated to
  `refs/heads/main`. It holds `contents: write` (release),
  `packages: write` (ghcr.io push and attestation referrers), and
  `id-token: write`, `attestations: write` and `artifact-metadata: write`
  for the provenance and SBOM attestations.

Its pull-request rehearsal, `release-dry-run`, keeps the read-only default
and uses no secrets. `nightly-status` holds `issues: write` and nothing else;
it runs only for the `schedule` event and executes only
`.github/scripts/tracking-issue.sh` (sparse checkout). The trackers' `status`
jobs are the same.

Junction ref tracking never runs on `pull_request`: the old `track-refs` job,
gated on `startsWith(github.head_ref, 'renovate/')` (a branch name is not an
identity), pushed junction bumps onto whatever PR branch was open.
`track-junctions.yml` runs on a schedule and opens its own PR.

The `build` job (validation, compile, signing) runs with the read-only default
on every event. `changes` adds only `pull-requests: read`, to list a pull
request's files. If a new job needs additional permissions, keep them as
narrow as possible and document why.

### `sudo` scope

Use rootless podman in build jobs wherever possible. Only use `sudo podman` when
the step genuinely requires root (e.g. BST artifact cache access). Do not mix
`sudo podman` and plain `podman` within the same job — pick one based on what the
runner supports and stay consistent. The Justfile's `sudo_cmd` is empty when
rootless `podman info` works and `sudo` otherwise.

### No PATs; GitHub App tokens for automation that must trigger CI

- Personal Access Tokens (PATs) are banned, except Prow's `PROW_TOKEN`
  ("Prow token" in [merge-queue.md](merge-queue.md)).
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
job outside this table reads a secret or a listed job loses its environment;
`PROW_TOKEN` is the one exception ("Prow token" in [merge-queue.md](merge-queue.md)).

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

`main` merges only through the merge queue; its required checks are in [merge-queue.md](merge-queue.md).

| Job | Workflow | Trigger | Purpose |
|-----|----------|---------|---------|
| `track-junctions` | `track-junctions.yml` | `schedule` (08:00 UTC), `workflow_dispatch` | Resolves the `freedesktop-sdk.bst` junction ref, syncs `project.conf`'s `installer-version`, and opens/updates its own PR on `auto/track-junctions`. Read-only `GITHUB_TOKEN`; the push and the PR use the mergeraptor app token (`trackers` environment), minted after `just bst source track` and narrowed to `contents` + `pull-requests`. Never on `pull_request`. |
| `changes` | `build.yml` | `pull_request` (`opened`, `synchronize`, `reopened`, `labeled`), `merge_group`, `push/main`, `schedule` (05:30 UTC), `workflow_dispatch` | Decides what the run builds. `release=true` only for a push or dispatch on `main`; it is the one switch that hands out the signing secrets, picks the release version and publishes. `image=true` (full `build` + `boot-test`) for releases, the nightly schedule and dispatches; for a merge group whenever its changed files can reach the image set (see [merge-queue.md](merge-queue.md)); on a pull request only with the `full-build` label or when it changes `elements/freedesktop-sdk.bst` or `patches/`, and never when `.github/scripts/image-build-needed.py`, checked out from the PR's base revision (the job itself comes from the PR head; see [Build time and caches](ci-tooling.md)), finds no changed path that can reach the image set or the boot test (see [Build time and caches](ci-tooling.md)). `validate=true` for every merge group and every pull request event except adding an unrelated label. `contents: read` + `pull-requests: read`. |
| `validate` | `build.yml` | `pull_request`, `merge_group` | `just validate` with throwaway keys: resolves every shipped element graph and runs the version-invariant checks, in minutes. Read-only token. |
| `boot-test-preflight` | `build.yml` | when `changes` says `image=true` | Installs the boot test's tools with the same `scripts/ci/install-qemu-ovmf.sh` as `boot-test`, then runs `scripts/ci/dogfood-preflight.sh`: every host tool the dogfood scripts `boot-test` runs must be on the `PATH`, the OVMF files present and `/dev/kvm` read-writable. Each name its tool pattern matches in those scripts must be listed there, as a host tool or as one the runner never runs, so a new tool fails this job until it is. About a minute; `build` waits for it, so a missing tool (#486: `mcopy`) fails before the build instead of after it. Read-only token. |
| `build` | `build.yml` | when `changes` says `image=true` | Resolves the element graph, sets `image-version`, and runs the full BuildStream compile of the image set (OS DDI, signed UKIs, netboot ESP, k0s/KubeStellar/kubeadm/OpenZFS/NVIDIA sysext assets), which also writes and signs the combined `SHA256SUMS` inside `oci/bluefin-server-image.bst`. For releases it runs in the `release` environment and installs its `BOOT_KEYS_TARBALL` and `SYSUPDATE_SIGNING_KEY` secrets; both are required there. Other builds use no environment. Every other build uses throwaway keys and also exports two higher-versioned sets (`1.<run>.1`, `1.<run>.2`) for the update test. It uploads each set in parts by what its consumers read: `dist/diskless/` as `image-set-netboot` (OS DDI, netboot UKI and ESP), `-installer`, `-sysupdate` (usr, usr-verity, disk UKI) and `-sysexts` (`*.raw.zst`), plus the catch-all `image-set-core` that excludes exactly what the others include, so no file is ever dropped; `1.<run>.1` as `image-next-boot` (catch-all) and `image-next-update` (sysupdate sources and sysexts); `1.<run>.2` as `image-broken`; the Ignition test signatures as `ignition-sigs`. The update sets leave out the installer. `image-check`, `release` and `release-dry-run` merge every `image-set-*` part back into `dist/diskless/`; `tests/unit/test_ci_image_artifacts.py` keeps the split exhaustive. Read-only token. |
| `boot-test` | `build.yml` | after `build` | Runs the Secure Boot QEMU checks on the exported sets (see Core Process step 4), with the harness checked out at the commit `build` built. A `fail-fast: false` matrix over the buckets of `scripts/ci/boot-test.sh`, one runner each, so its checks are `boot-test (<bucket>)`; each bucket downloads only the `build` artifacts its scenarios read, as listed in its matrix entry. Each bucket's wall time, passed or failed, is a notice and a row of its step summary. On failure each bucket uploads its logs as `boot-test-logs-<bucket>`. Read-only token. |
| `boot-test-result` | `build.yml` | after `boot-test`, when `build` succeeded | The one result of every `boot-test` bucket: fails unless `boot-test` succeeded. `release` and `nightly-status` gate on it, and it is skipped like `boot-test` when nothing was built, so it is the boot test's required check. No checkout, `permissions: {}`. |
| `image-check` | `build.yml` | after `build` | Runs `.github/scripts/check-image.py` on the built image set: no missing libraries, required dlopen libraries, or unit/udev programs in `/usr`, the disk UKI's initrd, or the sysexts (resolved over `/usr`); the step summary diffs `/usr` paths against the latest release. Then `scripts/ci/image-sizes.py` tables the size of every file, the disk UKI's `.linux` and `.initrd` and the unpacked initrd against the latest release's `bluefin-server_<ver>.size.json` (or its `*.usr.raw` alone), with a `::warning::` for each that grew by more than 5 % or 5 MiB (never a failure), and uploads this set's report as the `image-size` artifact that `release` and `release-dry-run` publish with the set, unsigned (see "Publishing" in `systemd-sysupdate-verification.md`). `release` needs it. Read-only token. |
| `release` | `build.yml` | `release=true` | Publishes `dist/diskless/` as-is through `scripts/publish-release.sh`: an immutable GitHub Release tagged `v<image-version>` plus an ORAS OCI artifact at `ghcr.io/<owner>/bluefin-server:<ver>,latest` (one layer per file, artifact type `application/vnd.projectbluefin.server.release.v1`), with provenance and SBOM attestations for both. It runs only when `build`, `boot-test-result` and `image-check` succeeded (`!cancelled()` plus each job's result, so a failed `kernel-cache` does not hold it back), and marks the set latest (GitHub "Latest", ghcr `latest`) only when no newer version is published (see "Publishing" in `systemd-sysupdate-verification.md`). Write permissions listed above. Main runs queue, so a merge that edits `build.yml` can land before an earlier run publishes; GitHub then refuses `GITHUB_TOKEN` a tag at that run's commit (it would need the `workflows` permission). `publish-release.sh taggable` detects this before anything is published and skips that version with a warning; the newer run releases its content. |
| `release-dry-run` | `build.yml` | `pull_request` or `merge_group` that builds | Runs the same `scripts/publish-release.sh` commands against the PR's or merge group's image set, with `image-check`'s size report when that job passed: verify, render `gh release create`, and a real `oras push` to a `registry` service container (pinned by digest) that it pulls back. Read-only token, no secrets. |
| `nightly-status` | `build.yml` | `schedule`, after `boot-test-result` and `image-check` | Opens the "Nightly build failing" issue (or comments on the open one) with the run URL when `changes`, `build`, `boot-test-result` or `image-check` failed, and closes it when a later nightly passes, through `.github/scripts/tracking-issue.sh` (finds the open issue by exact title). `issues: write` only. |
| `status` | `track-junctions.yml`, `track-binaries.yml`, `e2e-opt-in.yml` | after every other job, unless cancelled (`e2e-opt-in.yml`: `schedule` only) | The same script and semantics: "Junction tracker failing" / "Binary tracker failing" / "Opt-in feature e2e failing". `issues: write` only. |
| `docs` | `docs-checks.yml` | every `pull_request`, `merge_group`, `push/main` | Runs markdown and skill metadata checks via `docs-checks.py`. No `paths:` filter, so it can be a required check. Read-only token. |
| `release`, `e2e` | `e2e-opt-in.yml` | `schedule` (Wednesdays 09:00 UTC), `workflow_dispatch` (optional `release` tag) | QEMU end to end of the opt-in features the boot test never boots, on a published release: `release` resolves the latest release (or the dispatched tag); `e2e` is a `fail-fast: false` matrix over `scripts/ci/e2e-opt-in.sh --scenarios`, one runner each: `mdns` (two appliances resolve each other), `kubeadm` (single-node control plane with Cilium), `nvidia` (each driver flavour's sysext on a disk install, no GPU), `homelab-cluster`, `homelab-templates` and `homelab-installer` (the homelab sysexts as a two-node cluster from Ignition, from the published templates, and from the USB installer's Homelab entries). Each checks out the release's tag, downloads the set to `/mnt`, verifies it with `publish-release.sh verify` against the committed release keyring, and runs one dogfood script; the guests need internet. `e2e-opt-in.sh --install-tools` adds swtpm, xfsprogs and helm (pinned by version and sha256, bumped by hand) to what `install-qemu-ovmf.sh` installs. Logs upload as `e2e-logs-<scenario>`. Never on `pull_request`; nothing built or published. Read-only token. |
| `reproducibility` | `reproducibility.yml` | `schedule` (Mondays 09:00 UTC), `workflow_dispatch` | Builds the image set, deletes the final-assembly artifacts, rebuilds them without remote caches and diffs every output except `*.gpg` (see "Reproducible builds" in `ddi-installer-build.md`). Throwaway keys, nothing published. Read-only token. |
| `unit`, `go` | `unit-tests.yml` | every `pull_request`, `merge_group`, `push/main` | `unit` runs `just lint-python` (see [Python lint](#python-lint)), then the pytest and BATS suites, then the `root`-marked tests under `sudo`; `go` runs `gofmt -l`, `go vet` and `go test -race` for each Go module in the repository (a matrix; `tests/unit/test_ci_workflows.py` fails if a `go.mod` is missing from it). No `paths:` filter, so both can be required checks. Read-only token. |
| `actionlint`, `zizmor` | `lint-actions.yml` | every `pull_request`, `merge_group`, `push/main` | Lint the workflows (see [Workflow linting](#workflow-linting)). Read-only token; zizmor uses it for its online audits. |
| `authorize` | `prow.yml` | `issue_comment` | Calls `projectbluefin/.project`'s reusable `prow-authorize.yml` (pinned by SHA) to look the commenter up in the org's `maintainers.yaml` roster; its `triage` output unlocks `/triage`, `/priority` and `/label` for the `prow` job. A failed lookup blocks the comment's commands. `contents: read`. |
| `prow` | `prow.yml` | `issues`, `issue_comment`, `pull_request_target`, `pull_request_review`, `check_suite`, `schedule` (hourly) | Runs `cncf/prow-github-actions` v3.0.1 (pinned by SHA): `/` commands from the `prow-commands` allowlist, `needs-kind` on issues, reviewers and approvers from `OWNERS`, and merging through the merge queue once a PR has `lgtm` + `approved` (the hourly schedule is a backstop). `pull_request_target` is safe because nothing checks out or runs PR code. Write scopes granted per job. |
| `label-sync` | `prow.yml` | `workflow_dispatch`, `push` of a repository `.github/prow.yaml` (none exists) | Same reusable workflow with `jobs: label-sync`: syncs repository labels from the org config at `projectbluefin/.project/prow.yaml`. Run by hand after every change to that config. |
| `check`, `propose` | `track-binaries.yml` | `schedule` (08:30 UTC), `workflow_dispatch` | `check` finds the newest patch release in each pinned series of the upstream components pinned by version + sha256 (Kubernetes, cri-tools, containerd, runc, CNI plugins, k0s, each NVIDIA driver flavour inside its branch, Tailscale, NetBird, ORAS) or by version + git commit (NVIDIA Container Toolkit), and the newest dated snapshot of the IANA registries behind `/etc/protocols` and `/etc/services` (`iana-etc`, no series), with `.github/scripts/track-binaries.py`; `propose` moves each version together with its sha256 pins for every pinned architecture (amd64 and the `arch == "aarch64"` sources), verified against upstream's checksum files and the downloaded assets (a git commit: the GitHub API and `git ls-remote` must agree), and opens or updates one PR per component on `auto/track-binaries/<component>`. Minor bumps stay manual (`kubeadm-sysext.md`, `k0s-sysext.md`); a new NVIDIA branch is a new flavour (`nvidia-sysext.md`). Read-only `GITHUB_TOKEN`; writes use the mergeraptor app token (`trackers` environment, `propose` only), minted after the apply step and narrowed to `contents` + `pull-requests` (+ `workflows` for ORAS, pinned in `build.yml`). Never on `pull_request`. |

Both trackers commit, push and open or update their pull request through
`.github/scripts/propose-pr.sh`. It pushes nothing when the paths already
match `main`, or when an open PR's branch already holds the same content, so
a daily run neither force-pushes an identical commit nor restarts that PR's
build; `track-binaries` also passes `--skip-closed-title`, so a release
whose PR was closed is not proposed again.

