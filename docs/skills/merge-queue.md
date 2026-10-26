---
name: merge-queue
description: The merge queue on main and its required status checks. Use when adding, renaming or removing a CI job or matrix value that gates merges, changing the ruleset, or when a pull request sits in the queue without checks.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-25"
---
# Merge queue and required checks

## When to Use

- Adding, renaming or removing a job (or a matrix value) in `build.yml`,
  `unit-tests.yml`, `docs-checks.yml` or `lint-actions.yml`.
- Changing `.github/rulesets/main-merge-queue.json`.
- A merge group waits for checks that never start.

## When NOT to Use

- Workflow conventions in general (pins, permissions, secrets): see
  [ci-tooling.md](ci-tooling.md).

## Core Process

`main` takes changes only through GitHub's merge queue, configured by the
ruleset in `.github/rulesets/main-merge-queue.json` (squash, all-green
groups of up to five pull requests). The file is the source of the live
ruleset: change it in a pull request, then apply it as an admin step.

```bash
gh api --method POST repos/projectbluefin/server/rulesets --input .github/rulesets/main-merge-queue.json
# later changes: PUT to the ruleset's id instead
gh api repos/projectbluefin/server/rulesets --jq '.[] | select(.name == "main — merge queue") | .id'
```

Its required checks are bound to GitHub Actions (`integration_id` 15368),
so a commit status of the same name cannot satisfy one. Every workflow that
reports one runs on `pull_request` and `merge_group` without a `paths:` or
`branches:` filter: a check nothing reports holds the queue until
`check_response_timeout_minutes`. A skipped job reports as passing, so
every job a gate depends on is required too (a failed `changes` or
`boot-test-preflight` would otherwise skip everything below it into a
pass). `tests/unit/test_required_checks.py` fails if a required check is
not exactly one such job, or if a job of those workflows is neither
required nor listed as exempt with its reason. A job's check name is its
`name:` or, for a matrix, `<job> (<values>)`: renaming a job or a matrix
value means updating the ruleset in the same pull request and re-applying
it right after the merge.

The queue runs every check on the merge group's commit, which is what
`main` will be. `changes` classifies the group's changed files (the
compare API, at most 300; more always builds) with the base revision's
classifier and builds whenever the image set can change, label or not, so
no image change merges unbuilt. A pull request still builds before the
queue only with `full-build` or an FSDK change.

Enqueue by hand (*Merge when ready*), or let a GitHub App do it: GitHub
starts no workflow for an event `GITHUB_TOKEN` caused, so a merge group
that `github-actions` enqueued gets no checks and sits until the timeout.
Prow (`tide.merge_queue: auto` in the org config) enqueues with the
workflow's `GITHUB_TOKEN`; until it gets an app token, merge its `lgtm` +
`approved` pull requests by hand, and dequeue any entry `github-actions`
added.

## Red Flags

- A required check renamed in a workflow but not in the ruleset: every pull
  request waits on a check nothing reports.
- A `paths:` or `branches:` filter on a `merge_group` trigger.
- An entry in the queue enqueued by `github-actions`.

## Verification

- [ ] `python3 -m pytest tests/unit/test_required_checks.py` passes.
- [ ] After the merge, the live ruleset matches the file:
      `gh api repos/projectbluefin/server/rulesets/<id>`.
