---
name: ci-tooling
description: >
  CI workflow conventions for fsdk-containers. Use when writing or editing
  .github/workflows/*.yml, debugging a failing build job, or adding a new
  CI step.
metadata:
  context7-sources:
    - /websites/github_en_actions
    - /websites/cli_github_manual
---

# CI Tooling

## When to Use

- Writing a new workflow or job
- Adding a new action dependency
- Debugging a CI failure in the build, verify, or manifest job

## When NOT to Use

- Debugging a BST build failure (see `bump-fsdk-version.md`)
- Debugging `just verify` gate logic (see `verify-distroless.md`)

## Org Conventions

### Action pins — always use SHA, never mutable tags

Every `uses:` line must reference a full commit SHA. Never use `@v2` or `@main`.

```yaml
# correct
- uses: taiki-e/install-action@ace6ebe54a6a0c86dfb5f7764b17f793b6925bc3 # v2

# wrong — mutable tag, supply-chain risk
- uses: taiki-e/install-action@v2
```

Check sibling repos (`projectbluefin/dakota`, `projectbluefin/common`) for the
current pinned SHA of any action before adding it.

### Installing `just` — taiki-e/install-action, not snap/cargo/apt

```yaml
- uses: taiki-e/install-action@ace6ebe54a6a0c86dfb5f7764b17f793b6925bc3 # v2
  with:
    tool: just
```

### `sudo` scope

Use rootless podman in build and verify jobs wherever possible. Only use `sudo
podman` when the step genuinely requires root (e.g. BST artifact cache access).
Do not mix `sudo podman` and plain `podman` within the same job — pick one
based on what the runner supports and stay consistent.

The `sudo_cmd` Just variable auto-detects at recipe startup:

```just
sudo_cmd := if `podman info >/dev/null 2>&1 && echo 1 || echo 0` == "1" { "" } else { "sudo" }
```

### No PAT/App credentials in CI
- Personal Access Tokens (PATs) are banned.
- GitHub App token plumbing is not used for build handoff.
- `repository_dispatch` is not used for build handoff.
- Build/release triggers are driven cleanly by Renovate PR merges or manual dispatches.

## Workflow Structure

| Job | Workflow | Trigger | Purpose |
|-----|----------|---------|---------|
| `build-and-release` | `build.yml` | `pull_request` on all, `push/main`, `workflow_dispatch` | Validates element graph, resolves and tracks Renovate refs, builds full images on GitHub, and uploads artifacts to GitHub Releases on push to main. |

GitHub Actions runs the **complete BuildStream compilation pipeline** natively using the 74GB SSD at `/mnt` for storage and caching, with final output uploaded to GitHub Releases.

## Core Process

1. **Renovate tracking**: `renovate.json` is configured with a custom regex manager to scan BuildStream junction files (`freedesktop-sdk.bst` and `gnome-build-meta.bst`) using `git-refs` datasource.
2. **Auto-resolution**: On Renovate PRs, GitHub Actions automatically executes `just bst source track` to resolve raw tags to full `git-describe` refs and commits them back.
3. **Full Compilation**: Builds standalone DDI OS and installer images on every pull request (validation) and push to `main`.
4. **Version Derivation**: The release tag is derived with `just version`, which parses the pinned FSDK point release from `elements/freedesktop-sdk.bst`.
5. **Automated Publishing**: For pushes to `main` (like Renovate PR merges), GitHub Actions automatically generates a GitHub Release based on the current FSDK version and uploads all compiled binaries.
6. **Release Signing**: SHA256SUMS manifests are signed with the project GPG key stored in the `SYSUPDATE_SIGNING_KEY` repository secret. Detached `.gpg` signatures are uploaded alongside the manifests so `systemd-sysupdate` can verify them.


## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "It's just a minor version tag, supply-chain risk is low." | One compromised tag push owns every repo using it. Pin to SHA. |
| "I'll check what SHA other repos use later." | Check now — it's one `gh api` call and takes 10 seconds. |

## Red Flags

- Any `uses:` line with a mutable ref (`@v2`, `@main`, `@latest`)
- `sudo podman` in one job and plain `podman` in another job doing the same operation
- A new action not present in any sibling repo — check upstream first

## Verification

- [ ] Every `uses:` line has a full 40-char SHA and a `# vX` comment
- [ ] `just verify` passes locally (or in CI) after workflow changes
- [ ] No new mutable action refs introduced
- [ ] Release signing step uploads detached `.gpg` signatures for every `SHA256SUMS` manifest
- [ ] The signing secret name matches the one documented in `docs/skills/systemd-sysupdate-verification.md`
