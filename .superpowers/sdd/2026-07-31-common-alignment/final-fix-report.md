# Common-contract alignment final fix report

Date: 2026-07-31
Repository: `projectbluefin/server`

## Scope

This fix wave addressed the final-review findings for the common-contract
alignment. Source-of-truth checks used:

- `/var/home/jorge/src/common/labels.json`
- `/var/home/jorge/src/common/docs/skills/label-workflow.md`
- `projectbluefin/bonedigger/.github/workflows/lifecycle.yml@main`
- `projectbluefin/bonedigger/templates/*`
- `projectbluefin/common/.github/pull_request_template.md`
- The live `projectbluefin/server` label and issue/PR state

## Changes made

- Changed issue-form labels to catalog values:
  - bugs: `kind/bug`, `status/triage`
  - features: `kind/enhancement`, `status/discussing`
  - agent donations: `flow/agent-donation`
- Retained the donation form's exact `Workflow: Agent Donation` body marker.
- Removed `.github/workflows/bonedigger.yml`; the current upstream workflow
  applies the nonexistent `status/approved` label and is not a valid full
  lifecycle owner for this repository.
- Restored `.github/workflows/label-enforcement.yml` using the verified,
  full-SHA-pinned design-enforcement reusable workflow.
- Adapted the pull-request template for Bluefin Server, including
  `just validate` and `projectbluefin/server` CI instructions, while retaining
  canonical issue linkage, lifecycle, Conventional Commit, documentation, and
  attribution requirements.
- Updated the alignment design and implementation plan so they make no claim
  that this repository has a working full lifecycle caller. The common
  lifecycle policy and valid label migration remain documented.
- Did not change live GitHub labels, issues, or pull requests.

## Verification

All focused checks passed:

- `actionlint .github/workflows/label-enforcement.yml`
- `actionlint .github/workflows/*.yml`
- `python .github/scripts/docs-checks.py`
- Focused `pre-commit run --files ...` for changed templates, workflow, and
  alignment documents
- `git diff --check`
- `just validate`
- YAML parsing and label-catalog verification for all issue forms
- Workflow/template scan for invalid labels, mutable refs, and the removed
  bonedigger caller
- Live label comparison: 67 common labels exactly match 67 server labels
- Live active-state verification: issues #6, #13, and #14 remain
  `status/triage`; no open pull requests; no comments or assignments made

## Concerns and follow-up

- The upstream bonedigger templates still contain labels that are not in the
  common catalog; these local copies intentionally normalize those labels until
  the upstream templates are corrected.
- No compatible full lifecycle reusable workflow is currently installed for
  this repository. Revisit the caller only after a verified owner and contract
  exist.
- Unrelated dirty worktree changes were preserved and were not staged.
