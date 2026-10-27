---
name: merge-queue
description: The merge queue on main and its required status checks. Use when adding, renaming or removing a CI job or matrix value that gates merges, changing the ruleset, or when a pull request sits in the queue without checks.
metadata:
  type: reference
  status: stable
  last_updated: "2026-10-27"
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

### Who enqueues

| Pull requests | Enqueued by |
|---|---|
| Renovate's digest, pin, patch and minor updates | GitHub auto-merge, which Renovate enables (`platformAutomerge: true` in `renovate.json`) and which enqueues as the mergeraptor app once the pull request's required checks pass. The org-inherited Renovate config sets `platformAutomerge: false`; with it Renovate merges directly and the queue refuses (405). |
| Anything with `lgtm` + `approved` | Prow, with `PROW_TOKEN` (below) |
| The rest (Hive's, the trackers', a maintainer's own) | A maintainer, with *Merge when ready* |

Hive's auto-merge sweeps merge directly; behind the queue they record a
`merge-queue-required` skip, so its pull requests wait for Prow or a person.

### Prow token

GitHub starts no workflow for an event `GITHUB_TOKEN` caused, so a merge
group that `github-actions` enqueued gets no checks and sits until the
timeout. Prow (`tide.merge_queue: auto` in the org config) therefore acts
with `PROW_TOKEN`, passed as the `token` secret of the `prow` job in
`prow.yml`: a classic PAT with the `repo` scope, the one exception to the
PAT ban in [ci-tooling.md](ci-tooling.md). `label-sync` and `authorize`
keep `GITHUB_TOKEN`.

- It is a repository secret, not an environment one: a job that calls a
  reusable workflow cannot name an environment. Any same-repository branch
  could read it, so its owner should be a machine user with write on this
  repository and nothing else. `tests/unit/test_ci_workflows.py` fails if
  any other job names it.
- Everything Prow writes (labels, comments, the `prow/lgtm` status, queue
  entries) is the token owner's, and fires events as a person's would:
  Prow's own label writes now start `pull_request` runs (`build.yml`'s
  `changes` skips them in seconds).
- Prow dequeues only entries whose enqueuer is `github-actions` or a
  `[bot]`, so it no longer removes its own entries when a pull request
  loses `lgtm` or gets `/hold`: dequeue those by hand.
- When the token expires or is revoked, Prow's runs fail and nothing is
  enqueued; enqueue by hand (*Merge when ready*) until it is replaced:
  `gh secret set PROW_TOKEN --repo projectbluefin/server`.

## Red Flags

- A required check renamed in a workflow but not in the ruleset: every pull
  request waits on a check nothing reports.
- A `paths:` or `branches:` filter on a `merge_group` trigger.
- An entry in the queue enqueued by `github-actions`: Prow ran without
  `PROW_TOKEN`.

## Verification

- [ ] `python3 -m pytest tests/unit/test_required_checks.py` passes.
- [ ] After the merge, the live ruleset matches the file:
      `gh api repos/projectbluefin/server/rulesets/<id>`.
