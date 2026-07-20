---
name: ci-tooling
description: CI workflow conventions for Bluefin Server. Use when writing or editing .github/workflows/*.yml, debugging a failing build job, or adding a new CI step.
metadata:
  type: reference
  status: stable
  last_updated: 2026-07-20
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
# correct
- uses: taiki-e/install-action@c7eb1735f09259a5035e8e5d44b1406b1cddc0fb # v2

# wrong — mutable tag, supply-chain risk
- uses: taiki-e/install-action@v2
```

Check `.github/workflows/build.yml` (and sibling repos such as
`projectbluefin/dakota` and `projectbluefin/common`) for the current pinned SHA
before adding an action.

### Installing `just` — taiki-e/install-action, not snap/cargo/apt

```yaml
- uses: taiki-e/install-action@c7eb1735f09259a5035e8e5d44b1406b1cddc0fb # v2
  with:
    tool: just
```

### Workflow permissions

The release job in `.github/workflows/build.yml` uses:

```yaml
permissions:
  contents: write
```

That single permission is sufficient for the workflow to resolve and push
BuildStream refs, create GitHub Releases, and upload release assets. If a new
job needs additional permissions, keep them as narrow as possible and document
why.

### `sudo` scope

Use rootless podman in build jobs wherever possible. Only use `sudo podman` when
the step genuinely requires root (e.g. BST artifact cache access). Do not mix
`sudo podman` and plain `podman` within the same job — pick one based on what the
runner supports and stay consistent.

The `sudo_cmd` Just variable auto-detects at recipe startup:

```just
sudo_cmd := if `podman info >/dev/null 2>&1 && echo 1 || echo 0` == "1" { "" } else { "sudo" }
```

### No PAT/App credentials in CI

- Personal Access Tokens (PATs) are banned.
- `repository_dispatch` is not used for build handoff.
- Build/release triggers are driven cleanly by Renovate PR merges or manual
  dispatches. The workflow uses `secrets.GITHUB_TOKEN` for release uploads.

## Workflow Structure

| Job | Workflow | Trigger | Purpose |
|-----|----------|---------|---------|
| `build-and-release` | `build.yml` | `pull_request`, `push/main`, `workflow_dispatch` | Resolves the element graph, runs the full BuildStream compile, and uploads DDI/installer/sysext assets to GitHub Releases on push to `main`. |

GitHub Actions runs the **complete BuildStream compilation pipeline** using `/mnt`
SSD storage on the runner for podman and BuildStream caches. Release assets are
uploaded to a GitHub Release tagged `installer-v<FSDK-RELEASE>`.

## Core Process

1. **Renovate tracking:** `renovate.json` is configured with a custom regex
   manager to scan BuildStream junction files (`freedesktop-sdk.bst` and
   `gnome-build-meta.bst`) using the `git-refs` datasource.
2. **Auto-resolution:** On Renovate PRs, GitHub Actions executes
   `just bst source track` to resolve raw tags to full `git-describe` refs and
   commits them back to the PR branch.
3. **Full Compilation:** Builds the standalone DDI OS image, live installer, and
   k3s systemd-sysext on every pull request and push to `main`.
4. **Version Derivation:** The release tag is derived with `just version`, which
   parses the pinned FSDK point release from `elements/freedesktop-sdk.bst`.
5. **Automated Publishing:** For pushes to `main` (including Renovate PR merges),
   GitHub Actions creates a GitHub Release, uploads all compiled assets, and
   produces a combined `dist/release/SHA256SUMS` plus detached
   `SHA256SUMS.gpg` for `systemd-sysupdate` verification.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It's just a minor version tag, supply-chain risk is low." | One compromised tag push owns every repo using it. Pin to SHA. |
| "I'll check what SHA other repos use later." | Check now — it's one `gh api` call and takes a few seconds. |

## Red Flags

- Any `uses:` line with a mutable ref (`@v2`, `@main`, `@latest`).
- `sudo podman` in one step and plain `podman` in another step doing the same
  operation.
- A new action not present in any sibling repo — check upstream first.

## Verification

- [ ] Every `uses:` line has a full 40-character SHA and a `# vX` comment.
- [ ] `just validate` passes after workflow changes.
- [ ] No new mutable action refs introduced.
- [ ] The release signing step uploads detached `.gpg` signatures for every
      combined `SHA256SUMS` manifest.
- [ ] The signing secret name matches the one documented in
      `docs/skills/systemd-sysupdate-verification.md`.
