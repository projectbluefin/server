---
name: skill-improvement
version: "2.0"
last_updated: "2026-07-19"
tags: [skills, improvement, documentation]
description: |
  Maintain the skill library and the work+learning loop. Load when adding,
  refactoring, or finishing a skill.
metadata:
  type: procedure
  status: stable
---

# Skill Improvement Mandate

Every agent session produces two outputs:

1. **The work** — the element, fix, or image.
2. **The learning** — what a future agent needs to know.

Output 1 without Output 2 leaves the project no smarter.

## When to Use

Use when finishing any Bluefin Server task, deciding whether a discovery belongs
in `docs/skills/`, or reviewing a branch before handoff.

## What counts as a learning worth writing down

- A non-obvious FSDK behavior (e.g. "bash is in the `runtime` domain, not `shells`,
  so `compose exclude: shells` does not remove it").
- A size lever and its risk tier (what is safe to `rm`, what crashes at runtime).
- A build sandbox constraint (e.g. "`dracut` invokes `grep`/`sed`/`ldconfig`
  internally, so the script sandbox must include those tools even if your own
  commands don't name them").
- A versioning / lifecycle fact about tracking FSDK releases.

## What does NOT belong here

- Ephemeral session notes, changelog narration, personal scratch.
- Secrets or tokens.
- One-off task instructions.

## The loop

1. Do the work.
2. Ask: *what did I learn that the next agent would have to rediscover?*
3. Write it into the right `docs/skills/*.md` (or add a new one + link it in
   `README.md`).
4. Keep `just validate` green.

## Skill front-matter schema

Every `docs/skills/*.md` file begins with:

```yaml
---
name: <kebab-skill-name>
version: "2.0"
last_updated: "YYYY-MM-DD"
tags: [topic, subtopic]
description: |
  One sentence, ≤25 words, describing when to load this skill.
metadata:
  type: procedure | reference | guide | design-roadmap | index
  status: stable | draft | deprecated
  context7-sources:
    - /systemd/systemd
    - /apache/buildstream
  depends_on:
    - ddi-installer
    - systemd-sysupdate-verification
---
```

- `type`: tells the agent whether this is a how-to (`procedure`), lookup table
  (`reference`), judgment aid (`guide`), future design (`design-roadmap`), or
  routing file (`index`).
- `status`: `draft` for roadmap-only skills; `stable` for canonical facts;
  `deprecated` when a skill is kept for history but should not be loaded first.
- `context7-sources`: optional Context7 library IDs to resolve before
  implementing tool-specific changes.
- `depends_on`: skills that should be loaded depth-first before this one.

## How to add a new skill

1. Pick a file name matching the topic (`<kebab-topic>.md`).
2. Add front matter per the schema above.
3. Add an entry to `docs/skills/INDEX.md`.
4. Link from the relevant human docs (`README.md`, `CONTRIBUTING.md`, and any
   related skills).
5. Run link and line-count checks.

## How to refactor / split a skill

1. Identify the canonical file for the fact.
2. Move the fact; leave a forward link where it used to live.
3. Update `docs/skills/INDEX.md` if files are renamed or split.
4. Update `last_updated` on every touched skill file.

## Lazy-loading contract

Agents bootstrap in this order: `AGENTS.md` → `docs/skills/INDEX.md` → skill
file(s) → their `depends_on` skills. The index front matter is the
machine-readable routing table; the Markdown table below it is for humans.
Cross-reference facts instead of copying them.
