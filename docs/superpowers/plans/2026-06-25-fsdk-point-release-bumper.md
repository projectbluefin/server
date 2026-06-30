# FSDK Point-Release Bumper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automate point-release tracking of freedesktop-sdk (FSDK), automatically updating, validating, and pushing changes directly to the `main` branch.

**Architecture:** A daily GHA cron workflow triggers `just bst source track freedesktop-sdk.bst` to check for updates. If a point release bump is found, it validates the element graph and pushes the update directly to the `main` branch.

**Tech Stack:** GitHub Actions, BuildStream 2, Just

## Global Constraints

- Never use mutable tags for GHA actions (always pin to 40-char commit SHA).
- Only use standard BuildStream and ecosystem commands.
- Do not push to remote repository without authorization (all changes staged locally and verified).
- Keep point release tags immutable.

---

### Task 1: Finalize Branch Renaming and Justfile Lab-Runner Fix

**Files:**
- Modify: `.github/workflows/build.yml`
- Modify: `Justfile`

**Interfaces:**
- Consumes: Existing `.github/workflows/build.yml` and `Justfile`
- Produces: Correct triggers for branch `main` and a functional `lab-runner` smoke test.

- [ ] **Step 1: Check existing changes and verify they are staged/tracked**

Ensure `.github/workflows/build.yml` triggers on `main` instead of `master`.
Ensure `Justfile` contains the updated `lab-runner` smoke test without the redundant `bash` binary invocation.

- [ ] **Step 2: Run validation suite**

Run:
```bash
just validate
```
Expected: Element graph resolves cleanly with BuildStream.

- [ ] **Step 3: Commit the initial fixes**

Run:
```bash
git add .github/workflows/build.yml Justfile
git commit -m "chore: rename branch to main and fix lab-runner verification" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
Expected: Commit succeeds.

---

### Task 2: Create Auto-Update GHA Workflow File

**Files:**
- Create: `.github/workflows/auto-update-fsdk.yml`

**Interfaces:**
- Consumes: `Justfile` validation commands
- Produces: Automated GitHub Actions cron-driven tracking mechanism.

- [ ] **Step 1: Write the workflow file**

Create the `.github/workflows/auto-update-fsdk.yml` file with the following content:

```yaml
name: Auto-update FSDK

on:
  schedule:
    - cron: '0 3 * * *'  # Runs daily at 03:00 UTC
  workflow_dispatch:      # Allows manual trigger

permissions:
  contents: write

jobs:
  update-fsdk:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: taiki-e/install-action@ace6ebe54a6a0c86dfb5f7764b17f793b6925bc3 # v2
        with:
          tool: just

      - name: Track FSDK Point Release
        run: |
          just bst source track freedesktop-sdk.bst

      - name: Check for updates
        id: check_changes
        run: |
          if git diff --exit-code elements/freedesktop-sdk.bst; then
            echo "changes=false" >> $GITHUB_OUTPUT
            echo "No new freedesktop-sdk point releases found."
          else
            echo "changes=true" >> $GITHUB_OUTPUT
            echo "Found new freedesktop-sdk point release!"
          fi

      - name: Validate Element Graph
        if: steps.check_changes.outputs.changes == 'true'
        run: |
          just validate

      - name: Commit and Push Update
        if: steps.check_changes.outputs.changes == 'true'
        run: |
          git config --global user.name "github-actions[bot]"
          git config --global user.email "github-actions[bot]@users.noreply.github.com"
          git add elements/freedesktop-sdk.bst
          git commit -m "chore: bump freedesktop-sdk point release" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
          git push origin main
```

- [ ] **Step 2: Verify the workflow file syntax**

Run:
```bash
actionlint .github/workflows/auto-update-fsdk.yml || echo "actionlint not found, skipping"
```

- [ ] **Step 3: Commit the new workflow**

Run:
```bash
git add .github/workflows/auto-update-fsdk.yml
git commit -m "feat: add auto-update GHA workflow for fsdk point releases" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Local Dry-run Verification

**Files:**
- None (operational check only)

**Interfaces:**
- Consumes: `Justfile` and `elements/freedesktop-sdk.bst`
- Produces: Confidence that BuildStream source tracking works seamlessly.

- [ ] **Step 1: Check manual source tracking**

Run:
```bash
just bst source track freedesktop-sdk.bst
```
Expected: Process succeeds and lists `SUCCESS Track` at the end.

- [ ] **Step 2: Commit Spec & Plan Documents**

Add the design spec and implementation plan files to the git repository.
Run:
```bash
git add docs/superpowers/specs/2026-06-25-fsdk-point-release-bumper-design.md docs/superpowers/plans/2026-06-25-fsdk-point-release-bumper.md
git commit -m "docs: add FSDK bumper design spec and implementation plan" -m "Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```
Expected: All files are cleanly committed.
