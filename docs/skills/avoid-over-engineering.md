---
name: avoid-over-engineering
description: "Patterns to keep Bluefin Server simple. Use when reviewing for bloat, auditing for cuts, or before adding a new dependency/target/variable."
metadata:
  type: guide
---

# Avoid Over-Engineering

This repo favors the smallest thing that works. Before adding code, dependencies,
or abstraction, check whether the platform, standard library, or an existing tool
already does the job.

## Common cuts in this repo

### Prefer standard tools over hand-rolled loops

- Use `du -sb /path | cut -f1` instead of a `find` + bash arithmetic loop to sum
  file sizes. It is shorter, faster, and handles bind mounts correctly.
- Use `readlink -f`, `lsblk`, and bash pattern matching instead of pulling in
  `awk`, `grep`, or `sed` for simple disk discovery.

### Single source of truth for versions

Asset version strings (installer, DDI, release tags) must follow the FSDK point
release. Define one project variable in `project.conf` and reference it from
elements instead of hardcoding the same value in multiple files.

```yaml
# project.conf
variables:
  release-version: "25.08.13"
```

```yaml
# elements/oci/bluefin-server-ddi.bst
variables:
  ddi-version: "%{release-version}"
```

### Do not add unused build dependencies

- `compose` and `stack` elements with no commands should not declare tool-only
  build-depends such as `dracut.bst` or `make.bst`.
- Before removing a declared dependency, run `just validate` to confirm the graph
  still resolves, then build or run the relevant target if the dependency might
  be used at build time.

### Keep Justfile targets minimal

- Avoid aliases that just forward to another recipe (e.g. `export:` calling
  `just export-installer`).
- Avoid redundant validation targets; one `validate` target that resolves the
  whole graph is enough.
- Do not double-declare dependencies: if `export-installer` already depends on
  `build-installer`, `build:` should call `export-installer`, not both.

### Verify before and after cuts

The merge contract is `just validate`. Run it after removing dependencies or
simplifying commands. If a cut touches the installer or DDI pipeline, prefer a
full local build or cluster build before claiming the change is safe.

## What to do when auditing

1. Run `just validate` to establish a green baseline.
2. Apply the cut.
3. Run `just validate` again.
4. Update any docs or skill files that mention the removed target, dependency,
   or command.

## See also

- [skill-improvement.md](skill-improvement.md) — writing the learning down.
- [ddi-installer.md](ddi-installer.md) — installer-specific constraints.
