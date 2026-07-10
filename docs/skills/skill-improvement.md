---
name: skill-improvement
description: "The skill-improvement mandate for projectbluefin repos. Every session produces work + a skill update. Use when finishing any task, deciding whether a learning belongs in docs/skills, or verifying the work+learning loop before handoff."
metadata:
  type: procedure
---

# Skill Improvement Mandate

Every agent session produces two outputs:

1. **The work** — the element, fix, or image.
2. **The learning** — what a future agent needs to know.

Output 1 without Output 2 leaves the project no smarter.

## When to Use

Use when finishing any projectbluefin task, deciding whether a discovery belongs
in `docs/skills/`, or reviewing a branch before handoff.

## What counts as a learning worth writing down

- A non-obvious FSDK behavior (e.g. "bash is in the `runtime` domain, not `shells`,
  so `compose exclude: shells` does not remove it").
- A size lever and its risk tier (what is safe to `rm`, what crashes at runtime).
- A build sandbox constraint (e.g. "`find` is not available in the oci-builder
  sandbox — use shell globs").
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
4. Keep `just verify` green.
