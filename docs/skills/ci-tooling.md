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

### Personal Access Tokens (PAT) Ban & Mergeraptor Bot
Personal Access Tokens (PATs) are strictly banned in this organization. To perform cross-repository operations, trigger other workflows, or write back to branches, always generate a GitHub App installation token using the **Mergeraptor** app:

```yaml
- name: Get mergeraptor token
  id: app-token
  uses: actions/create-github-app-token@bcd2ba49218906704ab6c1aa796996da409d3eb1 # v3
  with:
    app-id: ${{ secrets.MERGERAPTOR_APP_ID }}
    private-key: ${{ secrets.MERGERAPTOR_PRIVATE_KEY }}
```

### Triggering Workflows (Pushes vs. Repository Dispatch)
Pushes made with the default `GITHUB_TOKEN` do **not** trigger other GitHub Actions workflows. To trigger downstream workflows or standard build runs from an automated update:
1. Push updates to an automated branch (e.g. `auto/update-fsdk`) and create a Pull Request using the Mergeraptor token.
2. Trigger the build workflow via a `repository_dispatch` event (e.g. `fsdk-updated`) using the Mergeraptor token as the authorization token.
3. Configure the build workflow's checkout step to accept a custom branch ref passed via `client_payload`:
   ```yaml
   - uses: actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2
     with:
       ref: ${{ github.event.client_payload.ref || github.ref }}
   ```

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
| `lab_repo` | `projectbluefin/testing-lab` | Target testing-lab repository |
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
