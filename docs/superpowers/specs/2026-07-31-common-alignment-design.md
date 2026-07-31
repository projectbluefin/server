# Bluefin Server Common-Contract Alignment

## Goal

Align `projectbluefin/server` with the canonical `projectbluefin/common` factory
contract without duplicating shared lifecycle rules or weakening Bluefin
Server-specific build and release constraints.

## Canonical sources

- `projectbluefin/common/labels.json` is the source of truth for GitHub labels.
- The shared label workflow defines the issue and pull-request lifecycle.
- `projectbluefin/bonedigger` owns synchronized issue/PR templates and their
  downstream propagation.
- Server documentation keeps only server-specific policy and links to those
  shared sources.

## Repository guidance

Update `AGENTS.md`, `CONTRIBUTING.md`, `.github/copilot-instructions.md`, and
`docs/skills/index.md` to:

- use namespaced common labels and the shared lifecycle;
- state that humans triage, approve, review, hold, and unblock work;
- state that agents claim only `status/queued` work and Clankers is transport
  only;
- point to the canonical common workflow instead of reproducing its taxonomy;
- retain server-specific FSDK, installer, DDI, sysext, validation, and
  ownership rules locally.

## GitHub automation and templates

Adopt the canonical synchronized issue/PR template set and template config.
Use the shared lifecycle caller rather than a server-local substitute that only
enforces design labels. Keep `build.yml` and `docs-checks.yml` server-owned.
Align Renovate's location and baseline policy with common while preserving the
custom BuildStream reference manager and server-specific dependency rules.

## Label migration

Synchronize the repository's live labels from the common label catalog. Map the
legacy labels before removal:

| Legacy label | Common lifecycle meaning |
| --- | --- |
| `1-triage` | `status/triage` |
| `2-discussing` | `status/discussing` |
| `3-clanker-queue` | `status/queued` plus the appropriate agent-routing label |
| `3-human-queue` | `status/queued` |
| `4-review` | `pr/needs-review` |
| `blocked` | `agent/blocked` |
| `hold` | `status/hold` |

Open issues and pull requests must retain their current intent during the
migration. Historical labels may be removed only after all active items are
mapped and the final label set is verified against `labels.json`.

## Validation

- Run the existing documentation checker and actionlint/pre-commit checks
  required by the repository.
- Verify every changed Markdown link and front-matter entry.
- Confirm the lifecycle caller and synchronized templates reference the
  intended common/bonedigger sources.
- Query GitHub labels and open issues/PRs after migration; confirm no active
  item is left without a valid lifecycle label.
- Review the final diff for accidental changes to server build/release
  behavior.

## Non-goals

- Do not move Bluefin Server build, release, installer, DDI, or sysext workflows
  into common.
- Do not duplicate the full common label taxonomy in local documentation.
- Do not write to `ublue-os/*`.
- Do not change issue content or post comments unless required by the approved
  label migration.
