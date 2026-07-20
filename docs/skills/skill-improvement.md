---
name: skill-improvement
description: How to add, split, rename, and refactor docs/skills files for Bluefin Server. Load this whenever documentation or skill structure is changing.
metadata:
  type: meta-skill
  status: stable
  last_updated: 2026-07-20
---
# Skill Improvement — How to Maintain Agent Docs

This is the meta-skill for the documentation loop. Any change that touches `AGENTS.md`, `docs/skills/index.md`, or any skill file must also update this meta-skill if the process itself changes.

## When to Use

- Adding a new skill.
- Splitting a skill that has grown too large.
- Renaming, merging, or deleting a skill.
- Changing skill front-matter schema or the lazy-loading contract.
- Updating CI doc checks.

## What counts as learning worth writing down

- A boundary that caught a bad change.
- A build or test command that every agent needs to know.
- A non-obvious failure mode and its fix.
- A convention that prevents duplication.

Write it once in the relevant skill. Do not paste the same fact into multiple files.

## What does NOT belong here

- A single project plan or release schedule — use GitHub issues or an architecture-roadmap reference file.
- Internal-only hostnames, private URLs, or proprietary names — docs must be generic and reusable.
- TODO or FIXME notes — move unfinished work to an issue before merging.

## The loop

1. Do the work.
2. Update the skill that matches the changed domain.
3. Update `docs/skills/index.md` if a skill is added, removed, renamed, or re-scoped.
4. Run the verification commands.
5. Hand off the work with the changed skill files listed explicitly.

## Skill front-matter schema

Every `docs/skills/*.md` file must start with:

```yaml
---
name: <kebab-case-name>
description: <≤ 1024 characters, says what this skill does and when to use it>
metadata:
  type: how-to | reference | meta-skill | index
  status: stable
  last_updated: "YYYY-MM-DD"
  context7-sources:        # optional, only when source-verified external docs are used
    - /org/project
---
```

Rules:
- `name` must match the filename stem.
- `name` is kebab-case, lowercase alphanumerics and hyphens only, ≤ 64 characters.
- `description` ≤ 1024 characters.
- No extra top-level front-matter keys; use `metadata` for anything else.
- `metadata.status: draft` is not allowed on `main`.

## How to add a new skill

1. Pick a kebab-case name that describes the task, not the component.
2. Create `docs/skills/<name>.md` with valid front-matter.
3. Keep the body ≤ 300 lines; 500 lines is the hard maximum.
4. Add a row to `docs/skills/index.md`.
5. If the task appears in `AGENTS.md` routing, add or update the link there.
6. Run verification.

## How to split a skill

A skill should split when it exceeds 300 lines or mixes a decision tree with long reference material.

1. Move the reference material into `docs/skills/<parent>-reference.md`.
2. Keep the decision tree, trigger words, and links in the original file.
3. Add the child file to `docs/skills/index.md` with a clear scope.
4. Update the parent's cross-reference line.

## How to refactor or rename a skill

1. Rewrite or rename the file.
2. Update every occurrence in `docs/skills/index.md` and `AGENTS.md`.
3. Add a redirect note at the old path only if external links exist; otherwise delete the old file.

## Lazy-loading contract

- `docs/skills/index.md` is loaded eagerly. It stays small.
- Each skill body loads only when its task triggers.
- Child reference files load only when the parent links to them.
- Cross-skill facts are resolved via one-line links, not copy-paste.

## Verification before handoff

- [ ] `just validate` passes (if any code or build element changed).
- [ ] No skill file exceeds 500 lines.
- [ ] No `TODO/FIXME/draft` markers remain in changed `.md` files.
- [ ] All internal Markdown links resolve.
- [ ] New or renamed skills are listed in `docs/skills/index.md` and `AGENTS.md`.
