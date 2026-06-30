# fsdk-containers — FSDK Point-Release Bumper (design)

Date: 2026-06-25
Status: approved

## Summary

This design introduces a fully automated GitHub Actions workflow (`auto-update-fsdk.yml`) that runs on a daily schedule to track, validate, and commit/push freedesktop-sdk point-release updates to the `main` branch. This eliminates the need for manual point-release branch tracking and pull requests while maintaining strictly immutable tags and automated rebuilds.

## Goals

- Automated checking of upstream `freedesktop-sdk` updates on the active branch line (`25.08*`).
- Automated point-release bump in `elements/freedesktop-sdk.bst` using BuildStream's native tracking capabilities.
- Local validation of the element graph to guarantee changes do not break downstreams before committing.
- Automated commit and direct push to the renamed default branch `main`.
- Self-rebuilding and tag publishing triggered by the automated push.

## Architecture & Implementation

### 1. The GitHub Actions Workflow (`.github/workflows/auto-update-fsdk.yml`)

The workflow runs on a daily cron schedule at `03:00 UTC` and supports manual triggers (`workflow_dispatch`).

```yaml
name: Auto-update FSDK

on:
  schedule:
    - cron: '0 3 * * *'
  workflow_dispatch:

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

### 2. Integration with Build & Publish

When a point-release bump is successfully pushed to `main`:
1. The standard `.github/workflows/build.yml` push trigger fires.
2. The dynamic tags (like `:latest`, `:25.08`, and the new point-release tag `:25.08.NN`) are auto-calculated from the updated `elements/freedesktop-sdk.bst`.
3. New container images are built, verified, and pushed to GHCR end-to-end.

## Verification

Before declaring work complete:
- [ ] Ensure `.github/workflows/auto-update-fsdk.yml` is successfully written.
- [ ] Rename the default branch from `master` to `main` locally and ensure workflow files point to `main`.
- [ ] Verify the changed `Justfile` passes validation with `just validate` and the `lab-runner` smoke test fix is correct.
