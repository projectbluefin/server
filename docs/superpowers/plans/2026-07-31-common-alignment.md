# Bluefin Server Common-Contract Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `projectbluefin/server` consume the canonical projectbluefin/common factory contract for documentation, lifecycle policy, templates, Renovate policy, and live GitHub labels.

**Architecture:** Keep Bluefin Server build, release, installer, DDI, sysext, and ownership rules local. Link shared lifecycle policy to common, consume bonedigger’s synchronized template structure with labels validated against the common catalog, and retain the local label-enforcement workflow. Do not install the incompatible bonedigger lifecycle caller while no verified full lifecycle owner is available. Migrate the live repository labels in a separate, verified step so active issues retain their meaning.

**Tech Stack:** Markdown/YAML/JSON5, GitHub Actions reusable workflows, GitHub CLI (`gh`), existing Python documentation checks, `actionlint`, `pre-commit`, and `just validate`.

## Global Constraints

- Compose from FSDK `components/*`; never use `platform.bst`.
- Keep the CPU baseline broad; do not introduce `x86_64_v3`.
- Keep the installer `systemd-sysinstall`-native; do not add custom installer scripts or non-native installers.
- Keep the running OS DDI shell-free except for the documented bring-up SSH exception.
- Use GPT `PARTUUID` boot entries; never hardcode block-device paths in boot configuration.
- Keep one canonical source per shared fact; link to common instead of copying its full label taxonomy or lifecycle rules.
- Do not write to `ublue-os/*`.
- Do not stage or revert the existing unrelated working-tree changes.

---

### Task 1: Align repository guidance with the shared lifecycle

**Files:**
- Modify: `AGENTS.md`
- Modify: `CONTRIBUTING.md`
- Modify: `.github/copilot-instructions.md`
- Modify: `docs/skills/index.md`

**Interfaces:**
- Consumes: `projectbluefin/common/docs/skills/label-workflow.md` and the local server hard constraints.
- Produces: concise local guidance that links to common for labels, lifecycle, ownership, and template synchronization.

- [ ] **Step 1: Replace duplicated lifecycle prose**

  In each of the four files, remove local label lists and lifecycle explanations that can drift. Keep the server-specific statement that humans triage/approve, agents claim only queued work, and Clankers only transports assignments, then link to:

  ```text
  https://github.com/projectbluefin/common/blob/main/docs/skills/label-workflow.md
  ```

  Also link template ownership to:

  ```text
  https://github.com/projectbluefin/bonedigger/blob/main/docs/skills/bonedigger-templates.md
  ```

- [ ] **Step 2: Add the shared workflow to the skills index**

  Add one routing-table row in `docs/skills/index.md` for the external common label workflow. Do not create a local duplicate of the shared taxonomy.

- [ ] **Step 3: Run the documentation checker**

  Run:

  ```bash
  python .github/scripts/docs-checks.py
  ```

  Expected: the checker exits 0 and all new common/bonedigger links resolve.

- [ ] **Step 4: Commit only this task’s files**

  ```bash
  git add AGENTS.md CONTRIBUTING.md .github/copilot-instructions.md docs/skills/index.md
  git commit -m "docs: align server guidance with common workflow"
  ```

### Task 2: Adopt canonical templates, local label enforcement, and Renovate layout

**Files:**
- Create: `.github/ISSUE_TEMPLATE/config.yml`
- Replace: `.github/ISSUE_TEMPLATE/bug-report.yml`
- Replace: `.github/ISSUE_TEMPLATE/feature-request.yml`
- Replace: `.github/ISSUE_TEMPLATE/help-this-project.yml`
- Create: `.github/pull_request_template.md`
- Restore: `.github/workflows/label-enforcement.yml`
- Delete: `.github/workflows/bonedigger.yml`
- Create: `.github/renovate.json5`
- Delete: `renovate.json`

**Interfaces:**
- Consumes: `projectbluefin/bonedigger/templates/{bug-report.yml,feature-request.yml,help-this-project.yml,config.yml}`, `projectbluefin/common/.github/pull_request_template.md`, the common label catalog, the prior local label-enforcement workflow, and the existing BuildStream custom Renovate manager.
- Produces: common-compatible downstream templates, local label enforcement, and Renovate configuration with server-specific dependency rules preserved. It does not install a full lifecycle caller.

- [ ] **Step 1: Copy the canonical issue templates**

  Replace the three local issue templates with the current structure from:

  ```text
  projectbluefin/bonedigger/templates/bug-report.yml
  projectbluefin/bonedigger/templates/feature-request.yml
  projectbluefin/bonedigger/templates/help-this-project.yml
  projectbluefin/bonedigger/templates/config.yml
  ```

  Preserve the filenames and place `config.yml` under `.github/ISSUE_TEMPLATE/`. Normalize their labels to the catalog: `kind/bug` plus `status/triage` for bugs, `kind/enhancement` plus `status/discussing` for features, and `flow/agent-donation` for donation requests. Retain the donation form’s `Workflow: Agent Donation` body marker because it is the exact marker used by bonedigger.

- [ ] **Step 2: Adapt the canonical pull-request template**

  Copy the exact current contents of:

  ```text
  projectbluefin/common/.github/pull_request_template.md
  ```

  Preserve its issue-linkage, lifecycle, Conventional Commit, validation, and
  AI-attribution requirements, while naming this repository as Bluefin Server,
  using `just validate`, and pointing CI checks at `projectbluefin/server`.

- [ ] **Step 3: Restore local label enforcement and remove the incompatible caller**

  Restore `.github/workflows/label-enforcement.yml` as the thin caller for the
  existing design-enforcement workflow:

  ```text
  projectbluefin/actions/.github/workflows/reusable-design-enforcement.yml@67d4cfb597e331448e31047a380439bdeee91865
  ```

  Use the prior issue and pull-request events, narrow permissions, and
  `secrets: inherit`. Delete `.github/workflows/bonedigger.yml`; the current
  bonedigger workflow applies the nonexistent `status/approved` label, and no
  compatible full lifecycle caller is available for this repository.

  ```yaml
  on:
    issues:
      types: [opened, edited, labeled, unlabeled]
    pull_request:
      types: [opened, reopened, synchronize, labeled, unlabeled]

  permissions:
    contents: read
    issues: write
    pull-requests: read
  ```

- [ ] **Step 4: Keep the local label-enforcement workflow**

  Keep the restored label-enforcement workflow as the only local workflow for
  issue/PR label enforcement. Keep `.github/workflows/build.yml` and
  `.github/workflows/docs-checks.yml` unchanged except for any required
  common-contract pinning or validation fixes.

- [ ] **Step 5: Merge the common Renovate baseline**

  Create `.github/renovate.json5` with the common baseline:

  ```json5
  {
    extends: ["config:recommended"],
    baseBranchPatterns: ["main"],
    branchPrefix: "renovate/",
    schedule: ["every monday between 00:00 and 03:00"],
    rebaseWhen: "never"
  }
  ```

  Preserve the server’s `custom.regex` manager for `elements/**/*.bst` and its `git-refs` package rules for freedesktop-sdk and gnome-build-meta. Add the common GitHub Actions digest pinning and automerge rules without adding common’s unrelated wallpaper or bonedigger managers. Delete the root `renovate.json` after the JSON5 file contains all required settings.

- [ ] **Step 6: Validate changed YAML/JSON5 structure**

  Run:

  ```bash
  actionlint .github/workflows/*.yml
  git diff --check
  ```

  Expected: actionlint and whitespace validation exit 0; no local workflow
  references the incompatible bonedigger lifecycle caller, and every template
  label exists in `common/labels.json`.

- [ ] **Step 7: Commit only this task’s files**

  ```bash
  git add .github/ISSUE_TEMPLATE .github/pull_request_template.md .github/workflows/bonedigger.yml .github/workflows/label-enforcement.yml .github/renovate.json5 renovate.json
  git commit -m "ci: align common templates and label enforcement"
  ```

### Task 3: Migrate the live GitHub label set

**Files:**
- No repository files; use read/write `gh` commands against `projectbluefin/server`.

**Interfaces:**
- Consumes: `projectbluefin/common/labels.json` and the active issue/PR list.
- Produces: the canonical common label set with active work mapped from legacy labels.

- [ ] **Step 1: Verify the label clone command and snapshot active state**

  Run:

  ```bash
  gh label clone --help
  gh issue list --repo projectbluefin/server --state open --limit 100 --json number,title,labels
  gh pr list --repo projectbluefin/server --state open --limit 100 --json number,title,labels
  ```

  Expected before migration: issues #6, #13, and #14 use `1-triage`; no pull requests are open.

- [ ] **Step 2: Clone the canonical labels**

  Run the verified `gh label clone` command from `projectbluefin/server` using `projectbluefin/common` as the source and its force/update option. If the installed `gh` version lacks `gh label clone`, use `gh api` to read `projectbluefin/common/labels.json` and idempotently create/update each label in `projectbluefin/server`; do not invent label names or colors.

- [ ] **Step 3: Map active issue labels**

  Replace `1-triage` with `status/triage` on every open issue that still carries it. Map any future active legacy labels using:

  ```text
  1-triage       -> status/triage
  2-discussing   -> status/discussing
  3-human-queue  -> status/queued
  3-clanker-queue -> status/queued (retain any other valid routing labels)
  blocked        -> agent/blocked
  hold           -> status/hold
  ```

  Do not add `pr/needs-review` to closed or merged pull requests.

- [ ] **Step 4: Clean stale historical labels**

  Remove the obsolete `4-review` label from historical closed/merged pull requests rather than replacing it with an active review state. Confirm no open pull request loses a required review label before deleting the legacy label names.

- [ ] **Step 5: Verify the final live state**

  Run:

  ```bash
  gh label list --repo projectbluefin/server --limit 100
  gh issue list --repo projectbluefin/server --state open --limit 100 --json number,labels
  gh pr list --repo projectbluefin/server --state open --limit 100 --json number,labels
  ```

  Expected: the repository label set matches `projectbluefin/common/labels.json`, no open issue carries a legacy numeric label, and no open PR is left without its intended review state.

### Task 4: Validate the complete alignment

**Files:**
- Review all changes from Tasks 1–3; do not modify unrelated user work.

**Interfaces:**
- Consumes: the updated docs, templates, workflow, Renovate file, and live labels.
- Produces: a verified common-contract alignment with no regression to server-specific automation.

- [ ] **Step 1: Run repository validation**

  Run:

  ```bash
  pre-commit run --all-files
  actionlint .github/workflows/*.yml
  python .github/scripts/docs-checks.py
  just validate
  ```

  Expected: every command exits 0. If a check fails because of an unrelated pre-existing dirty file, isolate the failure and do not rewrite that file.

- [ ] **Step 2: Review the final diff**

  Run:

  ```bash
  git diff --stat HEAD~3..HEAD
  git diff --check
  git status --short
  ```

  Confirm that only the alignment commits and intentional files changed, that no BuildStream element or release behavior changed accidentally, and that no internal-only hostnames or proprietary names were added to shared guidance.

- [ ] **Step 3: Recheck live GitHub lifecycle state**

  Confirm with `gh issue list` and `gh pr list` that active items use common lifecycle labels, no issue/PR was commented on or assigned unexpectedly, and no incompatible bonedigger lifecycle caller is present.

- [ ] **Step 4: Commit any validation-only fixes**

  If validation found an issue introduced by Tasks 1–3, fix only that issue and commit it with the matching Conventional Commit prefix. Do not amend the design commit or stage unrelated working-tree changes.
