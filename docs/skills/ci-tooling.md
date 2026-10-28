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
the tag; it stays a tag, not a digest pin. A failed upstream build leaves it
unpublished, so a fresh `bst2_image` bump can fail `just bst` with "manifest unknown".

### Python lint

`just lint-python`, which the `unit` job runs before the tests, runs ruff over
every Python file (`ruff.toml`: the E, F, W, I, UP and B rules, each disabled
rule with its reason) and mypy over `scripts/` and `.github/scripts/`
(`mypy.ini`: every function there is annotated). ruff's `target-version` is the
oldest interpreter that runs these files — today the runners' system python3, 3.14 — not the `setup-python` version the workflows install; raise it only when every caller runs that version or newer. Locally, install
the pinned tools into a virtualenv with
`python3 -m pip install -r .github/requirements-ci.txt`, run
`just lint-python`, and let `python3 -m ruff check --fix` apply the safe fixes.

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
| `changes` | `build.yml` | `pull_request` (`opened`, `synchronize`, `reopened`, `labeled`), `merge_group`, `push/main`, `schedule` (05:30 UTC), `workflow_dispatch` | Decides what the run builds. `release=true` only for a push or dispatch on `main`; it is the one switch that hands out the signing secrets, picks the release version and publishes. `image=true` (full `build` + `boot-test`) for releases, the nightly schedule and dispatches; for a merge group whenever its changed files can reach the image set (see [merge-queue.md](merge-queue.md)); on a pull request only with the `full-build` label or when it changes `elements/freedesktop-sdk.bst` or `patches/`, and never when `.github/scripts/image-build-needed.py`, checked out from the PR's base revision (the job itself comes from the PR head; see [Build time and caches](#build-time-and-caches)), finds no changed path that can reach the image set or the boot test (see [Build time and caches](#build-time-and-caches)). `validate=true` for every merge group and every pull request event except adding an unrelated label. `contents: read` + `pull-requests: read`. |
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
| `check`, `propose` | `track-binaries.yml` | `schedule` (08:30 UTC), `workflow_dispatch` | `check` finds the newest patch release in each pinned series of the upstream components pinned by version + sha256 (Kubernetes, cri-tools, containerd, runc, CNI plugins, k0s, each NVIDIA driver flavour inside its branch, Tailscale, ORAS) or by version + git commit (NVIDIA Container Toolkit), and the newest dated snapshot of the IANA registries behind `/etc/protocols` and `/etc/services` (`iana-etc`, no series), with `.github/scripts/track-binaries.py`; `propose` moves each version together with its sha256 pins for every pinned architecture (amd64 and the `arch == "aarch64"` sources), verified against upstream's checksum files and the downloaded assets (a git commit: the GitHub API and `git ls-remote` must agree), and opens or updates one PR per component on `auto/track-binaries/<component>`. Minor bumps stay manual (`kubeadm-sysext.md`, `k0s-sysext.md`); a new NVIDIA branch is a new flavour (`nvidia-sysext.md`). Read-only `GITHUB_TOKEN`; writes use the mergeraptor app token (`trackers` environment, `propose` only), minted after the apply step and narrowed to `contents` + `pull-requests` (+ `workflows` for ORAS, pinned in `build.yml`). Never on `pull_request`. |

Both trackers commit, push and open or update their pull request through
`.github/scripts/propose-pr.sh`. It pushes nothing when the paths already
match `main`, or when an open PR's branch already holds the same content, so
a daily run neither force-pushes an identical commit nor restarts that PR's
build; `track-binaries` also passes `--skip-closed-title`, so a release
whose PR was closed is not proposed again.

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
     [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md)). Two more runs install
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
- [ ] actionlint and zizmor (see [Workflow linting](#workflow-linting)) report
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
      match `docs/skills/systemd-sysupdate-verification.md`.
- [ ] A job that reads a secret names its main-only environment
      ([Environments and secrets](#environments-and-secrets)).
- [ ] Every `actions/checkout` sets `persist-credentials: false`.
