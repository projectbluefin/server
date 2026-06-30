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
PATs and GitHub App credentials are out of scope for this repo's CI design.
Use repository-native GitOps signals only:

1. Use `GITHUB_TOKEN` for same-repo writes (branch updates, PR creation, and tag creation).
2. Emit a Git ref signal that external automation can observe (for example `refs/tags/lab-build/<commit-sha>`).
3. Drive lab/cluster automation from observed Git state (tag/release/commit), not `repository_dispatch`.

## Workflow Structure

| Job | Workflow | Trigger | Purpose |
|-----|----------|---------|---------|
| `validate` | `build.yml` | `pull_request` only | `just validate` — element graph resolution, no build |
| `trigger-lab` | `build.yml` | `push/main`, `workflow_dispatch`, `repository_dispatch[fsdk-updated]` | Resolves HEAD SHA; calls `gh workflow run lab-release.yml --field ref=<sha>` |
| `dispatch-lab-build` | `lab-release.yml` | Daily 04:00 UTC schedule, `workflow_dispatch`, triggered by `trigger-lab` | Sends `repository_dispatch[lab-build-requested]` to `projectbluefin/testing-lab`; actual builds and zot pushes happen in the lab |

GitHub is the **control plane only** — no build compute runs here.

## Core Process

1. Keep workflow triggers explicit (`pull_request` validate vs push/dispatch delegation).
2. Resolve immutable refs (SHA/tag) in GitHub workflow and pass them as payload.
3. Dispatch build execution to lab workflows via authenticated GitHub API/CLI calls.
4. Keep actions SHA-pinned and token source aligned with org policy (Mergeraptor app for cross-repo writes).
5. Validate graph-only checks in GitHub and keep heavy build/push logic in lab.

### Daily schedule and manual trigger

`lab-release.yml` runs on a `schedule` cron (`0 4 * * *`, 04:00 UTC) and on
`workflow_dispatch`. Manual runs accept three optional inputs:

| Input | Default | Description |
|-------|---------|-------------|
| `ref` | `main` | Git ref to build (branch, tag, or SHA) |
| `zot_target` | _(empty)_ | Zot registry target prefix override |

The `concurrency.cancel-in-progress: false` guard on `lab-release` ensures an
in-flight release dispatch is never cancelled by a subsequent trigger.

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
