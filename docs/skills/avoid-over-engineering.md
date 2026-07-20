---
name: avoid-over-engineering
description: Use when reviewing for bloat, auditing for cuts, or before adding a new dependency, Justfile recipe, or BuildStream variable. Keeps Bluefin Server lean by preferring standard tools, single sources of truth, and minimal targets.
metadata:
  type: reference
  status: stable
  last_updated: 2026-07-20
---
# Avoid Over-Engineering

Bluefin Server favors the smallest thing that works. Before adding code,
dependencies, or abstraction, check whether the platform, a standard tool, or an
existing repo convention already does the job.

## When to Use

- Running a ponytail-style audit on the repo.
- Adding a new BuildStack dependency, Justfile recipe, or project variable.
- Reviewing a PR that introduces new tools, wrappers, or config flags.
- Refactoring an element or script and wondering what can be deleted.

## When NOT to Use

- Correctness, security, or performance reviews — route those to a normal review.
- Adding a genuinely new capability with no existing equivalent.
- Refactoring for readability alone when the current form is already minimal.

## Core Process

1. **Establish a green baseline.** Run `just validate` before changing anything.
2. **Identify the cut.** Look for:
   - Hand-rolled loops where a standard tool exists.
   - The same value hardcoded in more than one file.
   - Build dependencies declared but not used by the element.
   - Justfile recipes that only forward to another recipe.
   - Duplicate validation targets.
3. **Apply the smallest change.** Remove the dependency, collapse the target, or
   replace the loop with the standard tool.
4. **Re-validate.** Run `just validate`. For installer or DDI pipeline cuts,
   prefer a full `just build-installer` or cluster build before claiming safety.
5. **Update docs.** Remove or rewrite any skill file, AGENTS.md, or README line
   that references the deleted target, dependency, or command.
6. **Write the learning.** If the cut reveals a reusable pattern, update this
   skill file or add a new one and link it in `docs/skills/INDEX.md`.

## Common Rationalizations

| Rationalization | Reality |
|---|---|
| "A bash loop is more portable than `du`." | `du -sb` is POSIX and far faster; the loop is harder to read and easier to break. |
| "I'll hardcode the version here just this once." | The next FSDK bump will force someone to hunt down every copy. Use `project.conf`. |
| "This build-depend might be useful later." | Unused dependencies slow resolves and create false confidence. Add it when you need it. |
| "A forwarding recipe is harmless." | It duplicates the command surface and rots when the real recipe changes. |
| "I don't need to re-validate after a tiny cut." | `just validate` is the merge contract. Run it every time. |
| "This build dep isn't named in the commands, so it's unused." | `manual`/`script` element commands run in a sandbox that still needs `/bin/sh` and coreutils. Cutting the dep that supplies them breaks the build even if `make` itself is never called. |
| "The tool I depend on doesn't need grep/sed/etc." | Build tools like `dracut` invoke `grep`, `sed`, and `ldconfig` internally. If the sandbox doesn't have them, the tool fails with opaque "command not found" or missing-library errors. |

## Red Flags

- `for size in $(find ...)` loops summing bytes.
- The same version string in more than one `.bst` file.
- `build-depends` on tools in `compose`/`stack` elements with no commands.
- Justfile recipes whose entire body is `just <other-recipe>`.
- Multiple validation targets (`validate`, `validate-installer`, etc.).
- A recipe calling a dependency that another recipe already depends on.

## Verification

- [ ] `just validate` passes before and after the change.
- [ ] No hardcoded version duplicates remain; `release-version` in `project.conf`
      is the single source of truth.
- [ ] Removed build dependencies are not used by any command in the element.
- [ ] For `manual`/`script` elements, the sandbox still has `/bin/sh` and any coreutils the commands need after a dep cut.
- [ ] For `script` elements, build the element with `just bst build <element>`; transitive tools (`dracut`, `ukify`, etc.) may fail silently if their own runtime deps are missing from the sandbox.
- [ ] Justfile has no forwarding aliases or duplicate validation targets.
- [ ] Docs and skill files no longer reference deleted targets or dependencies.

## See also

- [skill-improvement.md](skill-improvement.md) — writing the learning down.
- [ddi-installer.md](ddi-installer.md) — installer-specific constraints.
