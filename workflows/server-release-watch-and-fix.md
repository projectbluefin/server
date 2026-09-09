# Workflow: Server Release Watch and Fix Loop

Specifies the automated loop that monitors GitHub Actions release runs on `projectbluefin/server`, verifies release contracts locally, detects regressions in build/staging/sysext configurations, and pushes fixes right until final release publication.

## Overview
- **Objective**: Ensure unattended or semi-attended continuous release delivery for Bluefin Server by watching in-flight CI runs, pre-emptively catching release-staging gaps, testing sysext and sysupdate contracts, and issuing targeted fixes.
- **Implementer**: Agent or headless GitHub Actions watcher bot with `gh`, `just`, and `git` access.

## Loop Attributes

### 1. Trigger
- **Type**: Event-driven (with periodic polling fallback).
- **Primary Event**: Push to `main` branch or manual `workflow_dispatch` triggering `.github/workflows/build.yml`.
- **Secondary Event**: GitHub Actions status notification (via webhook or CLI poll every 60s).

### 2. Actions & Stages

#### Stage A: Run Detection & Health Watch
1. Query active runs:
   ```bash
   gh run list --workflow=build.yml --limit 3 --json databaseId,status,conclusion,headSha,event
   ```
2. Track job-level progression (`build`, `track-refs`, `release`).
3. If run fails or is cancelled, fetch failed job logs immediately:
   ```bash
   gh run view --job=<failed-job-id> --log-failed
   ```

#### Stage B: Release Staging & Contract Audit
While the remote build is compiling in CI, audit the local tree against the release contract:
1. **Element Graph**: `just validate` (checks release version and k0s version alignment).
2. **Unit Suite**: `pytest tests/unit` and `bats tests/unit`.
3. **Docs & Skills**: `python3 .github/scripts/docs-checks.py`.
4. **Sysupdate Asset Parity**: Verify every `.transfer` target pattern in
   `files/os/sysupdate.d/*.transfer` and `files/os/sysupdate.k0s.d/*.transfer`
   is emitted by an element under `elements/` AND staged into `dist/release/`
   in `.github/workflows/build.yml`.

#### Stage C: Automated Remediation & Push
If an issue or drift is found (e.g. missing asset copy in `build.yml`, broken link, test mismatch):
1. Create a minimal fix branch:
   ```bash
   git checkout -b fix/release-<issue-slug>
   ```
2. Apply surgical fix following the Ponytail ladder (stdlib/native first, smallest diff).
3. Validate locally:
   ```bash
   just validate && pytest tests/unit && python3 .github/scripts/docs-checks.py
   ```
4. Commit with standard trailers:
   ```text
   fix(<scope>): <short description>

   Assisted-by: <Model> via GitHub Copilot
   Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
   ```
5. Push to GitHub (`git push --no-verify`) and open PR / merge per repo permissions.

#### Stage D: Release Verification
Once the GitHub Actions `release` job finishes:
1. Verify GitHub release exists:
   ```bash
   gh release view installer-v<version>
   ```
2. Check asset completeness:
   - `bluefin-server-installer-*.raw.zst`
   - `bluefin-server-*.efi`
   - `bluefin-server-ddi-*.raw.zst`
   - `k0s-*.raw.zst`
   - `SHA256SUMS`
   - `SHA256SUMS.gpg`
3. Verify GPG signature against `SHA256SUMS`.

### 3. Checkpoint (Push Right)
- **Position**: Post-release verification or unrecoverable CI failure.
- **Brief Format**:
  - **Release Status**: Published tag / release URL or Failed job name + failure log extract.
  - **Assets Verified**: Table of artifacts, sizes, and SHA256 matches.
  - **Action Required**: None if green; single binary decision (e.g., "Rerun failed job" or "Approve hotfix PR #NN") if blocked.
