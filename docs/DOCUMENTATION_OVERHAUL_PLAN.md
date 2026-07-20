# Documentation Overhaul Plan — Bluefin Server

> **Status:** Living plan.  
> **Scope:** agent-first repository documentation: root `AGENTS.md`, `docs/skills/`, and all supporting human-facing docs. Code changes are out of scope unless a doc requires a snippet to stay correct.

## 1. Executive Summary

Bluefin Server's documentation is already split into agent-facing skills (`docs/skills/`) and a root `AGENTS.md`, but the structure has drifted: the skill index uses custom front-matter, several files carry *draft/deprecated* flags, facts are duplicated across `README.md` and `AGENTS.md`, and line-count discipline is inconsistent. This plan makes the repo follow the best-documented agent-skill conventions available today:

- **Anthropic Skills** (`/anthropics/skills` via Context7) for skill file front-matter, naming, and three-level progressive loading.
- **Vercel Labs Skills** (`/vercel-labs/skills` via Context7) for discovery paths and `docs/skills/` layout conventions.
- **Toss Technical Writing** (`/toss/technical-writing` via Context7) for heading clarity and index-driven site structure.
- **AAIF-aligned root agent entry point** pattern, because Context7 has no AAIF-specific source. The existing `AGENTS.md` already matches the widely adopted root-agent shape (purpose, hard rules, build commands, skill routing, boundaries), so the plan hardens that rather than inventing a new format.

The result is one canonical doc per fact, lazy-loadable skills, enforced size budgets, and CI checks that keep the docs honest.

---

## 2. Research Summary & Sources

### Sources consulted via Context7

| Library ID | Relevance | Key guidance used |
|---|---|---|
| `/anthropics/skills` | High | SKILL.md **front-matter**: required `name` (kebab-case, ≤64 chars) and `description` (≤1024 chars); allowed top-level keys are `name`, `description`, `license`, `allowed-tools`, `metadata`, `compatibility`. **Three-level progressive loading**: metadata (~100 words) always in context; `SKILL.md` body loads when triggered, ideally <500 lines; bundled resources (scripts/references/assets) load on demand. References >300 lines should include a TOC. |
| `/vercel-labs/skills` | Medium | Skill discovery paths include `SKILL.md` at repo root, plus `skills/`, `skills/.curated/`, `skills/.experimental/`, `skills/.system/`, and agent-specific paths such as `.agents/skills/`. A root index/manifest file is the standard entry point for agents to list and route to skills. |
| `/toss/technical-writing` | Medium | Documentation sites benefit from an `INDEX.md` master navigation, clear page titles, and headings that immediately convey purpose. Use hierarchical structure with links to related pages. |
| Model Context Protocol spec (modelcontextprotocol.io) | Low for skill layout | Confirmed MCP is a JSON-RPC protocol for server/client context exchange. It does **not** define repository skill-file conventions, so this plan treats the Anthropic/Vercel skill conventions as the community pattern for agent skill files and notes the gap explicitly. |

### Gaps & tradeoffs

- **AAIF not in Context7.** No Context7 library returned for “AAIF agents.md standard” (only an unrelated payment-system match). The plan therefore treats the existing `AGENTS.md` shape as the AAIF-aligned community pattern and documents that choice. If an official AAIF spec is published later, `AGENTS.md` should be reconciled in one PR.
- **Token budgets.** Anthropic’s “<500 lines” skill body and “>300 lines needs TOC” are adopted as hard budgets. No Context7 source gave exact token limits, so these line budgets are the proxy.
- **Skill front-matter.** The current `docs/skills/INDEX.md` uses non-standard fields (`skills[].trigger`, `metadata.type: index`). The plan keeps a machine-readable routing table but renames the index schema to match Anthropic’s allowed keys where possible and reserves `metadata.type` for file classification.

---

## 3. Repository Audit

Audit scope: all `*.md` files under `/var/home/jorge/src/server`, excluding `.bst/staged-junctions/` and `node_modules/`.

| File | Lines | Classification | Notes / Action |
|---|---|---|---|
| `AGENTS.md` | 88 | **Rewrite** | Good AAIF shape, but duplicates README/what-is content and still lists “no shell” without the temporary-SSH exception context. |
| `README.md` | 173 | **Rewrite** | Human-facing entry point. Repeats build commands and factory role that should live only in skills. Tighten to trust/quick-start plus links. |
| `CONTRIBUTING.md` | 43 | **Rewrite** | Too terse. Point to `AGENTS.md` → `docs/skills/INDEX.md`, list the build contract, and link to the skill-improvement skill. |
| `docs/DOCUMENTATION_OVERHAUL_PLAN.md` | — | **Keep / update** | This file. Becomes the canonical execution plan. |
| `docs/MVP_1_0_READINESS.md` | 121 | **Keep / rewrite** | Valuable for release trust, but contains phase labels like “Phase A/B/C/D” that should be issue-tracker issues, not doc headings. Keep as release-readiness checklist. |
| `docs/skills/INDEX.md` | 105 | **Rewrite** | Convert to Anthropic-aligned manifest: kebab names, ≤1024-char descriptions, routing table, no narrative duplication. |
| `docs/skills/avoid-over-engineering.md` | 83 | **Keep** | Focused skill; under budget. |
| `docs/skills/architecture-roadmap.md` | 44 | **Keep** | Roadmap stub; acceptable as reference. |
| `docs/skills/bump-fsdk-version.md` | 89 | **Keep** | Focused how-to; under budget. |
| `docs/skills/ci-tooling.md` | 135 | **Keep / rewrite** | Contains useful workflow conventions but may duplicate `AGENTS.md` verification step. Cross-link instead. |
| `docs/skills/ddi-installer-build.md` | 131 | **Keep** | Build-specific installer reference; under budget. |
| `docs/skills/ddi-installer.md` | 171 | **Keep / trim** | Architecture explanation. If it grows past 300 lines, split into `ddi-installer.md` + `ddi-installer-reference.md`. |
| `docs/skills/factory-integration.md` | 113 | **Keep / update** | Should reference the new `bluefin-server-boot-test` Argo workflow in `projectbluefin/lab`. |
| `docs/skills/gap-analysis-architecture.md` | 26 | **Delete** | Already deprecated; content relocated. Remove from `INDEX.md`. |
| `docs/skills/gap-analysis-distros.md` | 201 | **Keep / update** | Source-verified comparison is useful for evaluators. Remove “draft” prose, mark stable, keep <=300 lines. |
| `docs/skills/k3s-sysext.md` | 121 | **Keep / trim** | Operating the sysext; check for duplication with `k3s-sysext-ops.md`. |
| `docs/skills/k3s-sysext-ops.md` | 120 | **Keep / trim** | Building the sysext. Reconcile overlap with `k3s-sysext.md`. |
| `docs/skills/skill-improvement.md` | 106 | **Rewrite** | Make this the canonical meta-skill per Anthropic conventions. Document how to add/split/refactor skills and maintain the index. |
| `docs/skills/system-containers.md` | 103 | **Keep** | Focused; under budget. |
| `docs/skills/systemd-sysext-extensions.md` | 112 | **Keep** | Focused; under budget. |
| `docs/skills/systemd-sysupdate-verification.md` | 134 | **Keep / rewrite** | Source-verified; cross-link with `factory-integration.md` and MVP readiness doc. |
| `docs/skills/tpm2-credential-sealing.md` | 73 | **Keep / update** | Marked with TODO flags; resolve them or split into issue tracker, then remove flags. |
| `.pytest_cache/README.md` | 8 | **Delete** | Generated cache file; not source docs. |

### Stale / contradictory / internal-only content to remove

1. **“No shell in the running OS DDI image” hard rule** — now a temporary exception because SSH is enabled for bring-up. `AGENTS.md` and `README.md` must state the exception and link to `factory-integration.md`.
2. **Duplicate build command lists** — they currently appear in `README.md`, `AGENTS.md`, and `ci-tooling.md`. Canonical list lives in `AGENTS.md`; everything else links.
3. **`gap-analysis-architecture.md`** — deprecated wrapper; delete.
4. **TODO/FIXME/draft flags in `.md` files** — `gap-analysis-distros.md`, `architecture-roadmap.md`, `INDEX.md`, `skill-improvement.md`, `tpm2-credential-sealing.md`. Resolve or move to issues; docs ship without TODO marks.
5. **Any “we”, “our”, or internal-only hostnames / infra names** — not currently present outside skill loading examples, but scan again during rewrite.

---

## 4. Target Structure

```text
/var/home/jorge/src/server
├── AGENTS.md                          # Root AAIF-aligned agent entry point (≤200 lines)
├── README.md                          # Human trust/quick-start + badges (≤200 lines)
├── CONTRIBUTING.md                    # Contributor checklist + learning loop (≤100 lines)
├── LICENSE                            # Existing license
│
├── docs/
│   ├── DOCUMENTATION_OVERHAUL_PLAN.md   # This plan (auditable, versioned)
│   ├── MVP_1_0_READINESS.md             # Release-readiness audit (≤150 lines)
│   │
│   └── skills/
│       ├── INDEX.md                     # Lazy-load manifest (≤150 lines)
│       ├── skill-improvement.md         # Meta-skill: how to maintain skills
│       │
│       ├── avoid-over-engineering.md
│       ├── architecture-roadmap.md
│       ├── bump-fsdk-version.md
│       ├── ci-tooling.md
│       ├── ddi-installer.md
│       ├── ddi-installer-build.md
│       ├── factory-integration.md
│       ├── gap-analysis-distros.md
│       ├── k3s-sysext.md
│       ├── k3s-sysext-ops.md
│       ├── system-containers.md
│       ├── systemd-sysext-extensions.md
│       ├── systemd-sysupdate-verification.md
│       └── tpm2-credential-sealing.md
│
└── .github/
    └── workflows/
        └── docs-checks.yml              # Optional: front-matter, link, budget CI
```

### Rationale by top-level item

- **`AGENTS.md`** — Mandatory root entry point per AAIF community pattern. Must load in a single context read.
- **`README.md`** — Human landing page. Optimized for trust (what it is, build status, quick start) and points agents to `AGENTS.md`.
- **`CONTRIBUTING.md`** — Human contributor path. Defers to `AGENTS.md` + `docs/skills/INDEX.md` so it never duplicates skill content.
- **`docs/skills/INDEX.md`** — The only file agents load after `AGENTS.md`. Small enough to keep in context while routing.
- **`docs/skills/skill-improvement.md`** — Meta-skill that teaches agents how to add, split, rename, and review skills.
- **`docs/DOCUMENTATION_OVERHAUL_PLAN.md`** — Living audit/execution record. Not a skill; can be long.
- **`docs/MVP_1_0_READINESS.md`** — External evaluator artifact. Not a skill; kept concise.
- **`docs-checks.yml`** (to be created) — Enforces budgets and front-matter schema on PRs.

---

## 5. Lazy-Loading Design for `docs/skills/`

### 5.1 Index / manifest (`docs/skills/INDEX.md`)

Agents load `AGENTS.md` first; `AGENTS.md` points to `docs/skills/INDEX.md`. The index is the only skill file loaded eagerly. It contains:

1. A short statement of purpose.
2. A machine-readable routing table with one row per skill.
3. A short loading contract (“load only the skill that matches your task; keep INDEX in context for cross-references”).

Index front-matter:

```yaml
---
name: skills-index
description: Lazy-load manifest for Bluefin Server skills. Load this file after AGENTS.md, then read only the skill that matches your current task.
metadata:
  type: index
  last_updated: "YYYY-MM-DD"
---
```

Routing table columns (no prose duplication):

| Skill file | When to load | One-line scope |
|---|---|---|
| `ddi-installer.md` | Installer boot flow, systemd-sysinstall, systemd-repart | High-level DDI install architecture |
| `factory-integration.md` | How Bluefin Server fits into downstream CI/lab infrastructure | Factory-consumer integration |
| `...` | ... | ... |

The table must fit in the 500-line file budget and the description in the front-matter must be ≤1024 chars.

### 5.2 Skill file naming & scoping

- **Name = filename stem = kebab-case** (matches Anthropic `name` validation). Examples: `ddi-installer.md`, `systemd-sysext-extensions.md`.
- **One skill per file.** If a skill exceeds 300 lines, split it: the parent skill keeps the decision tree, the child file keeps long reference material, and the child is linked from the parent.
- **No numbered prefixes** (e.g., `01-...`) — agents route by trigger words, not sort order.
- **Skills are mandatory, not optional** for the task they describe. If a topic is just background, put it in a `reference` child file and link it.

### 5.3 Front-matter conventions

Every skill file starts with:

```yaml
---
name: <kebab-case-name>
description: <≤1024 characters, states what this skill does and when to use it>
metadata:
  type: how-to | reference | meta-skill | index
  status: stable | deprecated | draft
  last_updated: "YYYY-MM-DD"
  context7-sources:        # optional, only when source-verified external docs are used
    - /org/project
---
```

Rules:
- `name` ≤64 chars, lowercase alphanumerics and hyphens only.
- `description` ≤1024 chars.
- No extra top-level keys; agent-specific tags go inside `metadata`.
- `metadata.status: draft` is forbidden on `main`. Use issues for unfinished work.
- `context7-sources` is optional and records external docs the skill relies on.

### 5.4 Cross-references without duplication

- Use one-line links: `See [factory-integration.md](factory-integration.md)`.
- Do not copy a fact into two skills. If a fact must appear in a human-facing file, link to the canonical skill.
- Keep a “Standing facts” section in `INDEX.md` only for ultra-stable one-liners (publish registry, version scheme). Anything longer belongs in a skill.

---

## 6. Token-Usage Optimization Rules

Enforced by `.github/workflows/docs-checks.yml` and honored by authors.

| Rule | Budget / Detail | Rationale |
|---|---|---|
| **Skill body line limit** | ≤300 lines preferred; absolute max 500 lines | Anthropic guidance; keeps skill body cheap to load. |
| **Reference child files** | >300 lines must split into `*-reference.md` with a TOC | Long reference material is loaded only when needed. |
| **Index size** | ≤150 lines | Eagerly loaded; must be small. |
| **Root `AGENTS.md`** | ≤200 lines | First doc loaded; should fit easily in context. |
| **Description length** | ≤1024 characters in front-matter | Metadata is always in context. |
| **Heading hygiene** | Every heading must state a concrete action or topic; no “Miscellaneous” or “Notes” | Toss Technical Writing principle. |
| **Canonical source** | One doc per fact; all others link | Prevents drift and duplicated token spend. |
| **When to link vs. inline** | Inline definitions only for terms defined in the current doc; everything else links | Reduces cross-loading. |
| **Tables over prose** | Prefer tables for comparisons and checklists | Dense, scannable, cheap. |
| **No TODO/FIXME/draft in docs** | Zero tolerance on `main` | Stale flags poison search and agent decisions. |
| **Code snippets** | Keep minimal and copy-pasteable; point to repo files for full examples | Avoids long pasted config. |

---

## 7. `AGENTS.md` Draft Contents

The final `AGENTS.md` should look like this. It is the canonical root entry point.

```markdown
# Bluefin Server — Agent Entry Point

Bluefin Server is an FSDK-based, image-based Linux server OS. It produces:
- an immutable XFS DDI OS payload (`oci/bluefin-server-ddi.bst`)
- an offline, systemd-native installer raw disk (`oci/bluefin-server-installer.bst`)
- an optional k3s `systemd-sysext` (`oci/k3s-sysext.bst`)

## What agents should know first

1. Read this file.
2. Load `docs/skills/INDEX.md` to route to the skill for your task.
3. Never guess label names, workflow secrets, or infra hostnames — check the relevant skill.

## Hard rules

1. Compose from FSDK `components/*`. Never use `platform.bst`.
2. Keep the CPU baseline broad: no `x86_64_v3`.
3. Installer must stay `systemd-sysinstall`-native; no custom installer scripts.
4. No shell in the running OS DDI image, except for the temporary SSH bring-up exception (see `docs/skills/factory-integration.md`).
5. Boot entries use GPT `PARTUUID`; never hardcode device paths.
6. One canonical source per fact; do not duplicate content across docs.

## Build / test commands

All targets run BuildStream inside the FSDK `bst2` container via `just bst`.

```bash
just validate              # merge-contract graph check (run this on every change)
just build-ddi             # local OS DDI payload build
just export-ddi            # export DDI artifacts
just build-installer       # local full installer build
just export-installer      # export installer + UKI
just build-sysext          # build k3s systemd-sysext
just export-sysext         # export sysext artifacts
just show-me-the-future    # local QEMU installer smoke test
```

## Skill routing

| Task | Skill |
|---|---|
| Build/debug installer or DDI | `docs/skills/ddi-installer.md`, `docs/skills/ddi-installer-build.md` |
| Factory integration / lab test workflows | `docs/skills/factory-integration.md` |
| systemd-sysext / confext | `docs/skills/systemd-sysext-extensions.md` |
| k3s sysext | `docs/skills/k3s-sysext.md`, `docs/skills/k3s-sysext-ops.md` |
| Versioning / FSDK bump | `docs/skills/bump-fsdk-version.md` |
| CI workflow conventions | `docs/skills/ci-tooling.md` |
| Add or refactor skills | `docs/skills/skill-improvement.md` |

## Documentation conventions

- Update only the skill that matches your change.
- Keep `AGENTS.md` small; do not list commands or deep context here.
- Remove `TODO/FIXME/draft` before merging; move unfinished work to issues.
- Use Conventional Commits. For doc-only changes: `docs:`.

## Boundaries

- Do not add Containerfiles or shell-based installers.
- Do not hardcode block device paths in boot configuration.
- Do not put Kubernetes or debug tooling in the base DDI if it can live in a sysext or system container.
- Do not duplicate a fact already in a skill.

## Verification

- [ ] `just validate` passes.
- [ ] Any changed skill is listed in `docs/skills/INDEX.md`.
- [ ] No new internal-only hostnames or proprietary names appear in `AGENTS.md` or skills.
```

---

## 8. Cleanup Execution Plan

### Phase 1 — Bootstrap the new entry point

1. Rewrite `AGENTS.md` using the draft in §7.
2. Rewrite `docs/skills/INDEX.md` with Anthropic-aligned front-matter and a routing table.
3. Rewrite `docs/skills/skill-improvement.md` as the meta-skill.

### Phase 2 — Genericize internal framing

1. Update `README.md` to human quick-start only; remove duplicated build tables.
2. Rewrite `CONTRIBUTING.md` to point to `AGENTS.md` → `docs/skills/INDEX.md`.
3. Update `docs/skills/factory-integration.md` with the temporary SSH exception and the lab boot-test workflow reference.

### Phase 3 — Chunk oversized skills

1. Review `ddi-installer.md` (171 lines), `gap-analysis-distros.md` (201 lines), `k3s-sysext.md` + `k3s-sysext-ops.md` for overlap. Split only if a single file exceeds 300 lines after trimming duplication.
2. Create child reference files only when required; otherwise trim.

### Phase 4 — Deduplicate and cross-link

1. Remove duplicate build command lists from `README.md` and `ci-tooling.md`; link to `AGENTS.md`.
2. Ensure `factory-integration.md`, `systemd-sysupdate-verification.md`, and `MVP_1_0_READINESS.md` cross-link rather than restate facts.
3. Resolve TODO flags in `tpm2-credential-sealing.md` or move to issues.

### Phase 5 — Human docs refresh

1. Trim `README.md` to ≤200 lines.
2. Convert `MVP_1_0_READINESS.md` phase headings into a checklist.

### Phase 6 — Validate

1. Run the docs-checks script locally (see §9).
2. Run `actionlint` if `.github/workflows/docs-checks.yml` is added.
3. `just validate` must still pass.

### Path mapping

| Old path | Action | New path / reason |
|---|---|---|
| `AGENTS.md` | Rewrite | same path |
| `README.md` | Rewrite | same path |
| `CONTRIBUTING.md` | Rewrite | same path |
| `docs/skills/INDEX.md` | Rewrite | same path |
| `docs/skills/skill-improvement.md` | Rewrite | same path |
| `docs/skills/gap-analysis-architecture.md` | Delete | content already moved to canonical skills |
| `docs/skills/gap-analysis-distros.md` | Update status, trim | same path |
| `docs/skills/factory-integration.md` | Update | same path |
| `docs/skills/tpm2-credential-sealing.md` | Update | same path |
| `docs/MVP_1_0_READINESS.md` | Rewrite | same path |
| `.pytest_cache/README.md` | Delete | generated cache |
| `.github/workflows/docs-checks.yml` | Create | new CI check (optional but recommended) |

---

## 9. Maintenance Model

### Ownership

- **Agent-facing structure (`AGENTS.md`, `docs/skills/INDEX.md`, skill-improvement skill):** doc maintainers own; changes require review by a doc maintainer *and* a subject-matter expert.
- **Domain skills:** the same owner as the code domain (installer, sysext, CI, etc.).
- **Human docs (`README.md`, `CONTRIBUTING.md`):** doc maintainers, with community feedback.

### Review triggers

Review docs whenever:
- `AGENTS.md` or any `docs/skills/*.md` changes.
- A new skill is added or a skill is split.
- Build/test commands or workflow names change.
- Hard rules or boundaries evolve.

### CI checks

Add `.github/workflows/docs-checks.yml` with these light checks:

| Check | Tool / method | Fail condition |
|---|---|---|
| Front-matter schema | `python -c`/`jsonschema` over YAML front-matter | Missing `name`, `description`, or unknown top-level keys; description >1024 chars; name not kebab-case or >64 chars. |
| Skill line budget | `wc -l` on `docs/skills/*.md` excluding `INDEX.md` and meta files | Any skill >500 lines. |
| Long-reference warning | `wc -l` | Any skill >300 lines emits a warning annotation. |
| Stale-flag scan | `grep -R` | Any `TODO/FIXME/draft` in `.md` on `main`. |
| Link validity | `markdown-link-check` or `lychee` | Broken internal links. |

### Skill improvement meta-skill

`docs/skills/skill-improvement.md` must teach agents:
- How to decide whether a topic needs a new skill or a reference child file.
- How to write front-matter that passes the schema.
- How to add an entry to `docs/skills/INDEX.md`.
- How to split a skill when it exceeds 300 lines.
- How to verify docs before handoff (`docs-checks`, `just validate`, `actionlint`).
- The rule: a skill is updated *before* the handoff that touches its topic.

---

## 10. Audience Mapping

| Audience | Primary docs | How the structure serves them |
|---|---|---|
| **External evaluators** (trust, release readiness) | `README.md`, `AGENTS.md`, `docs/MVP_1_0_READINESS.md`, `docs/skills/ci-tooling.md` | Quick scan of process, build trust signals, and verification checklists. |
| **Active contributors / agents** | `AGENTS.md`, `docs/skills/INDEX.md`, task-specific skills | Fast routing: load only the skill that matches the current task. |
| **Downstream maintainers** | `docs/skills/factory-integration.md`, `docs/skills/architecture-roadmap.md`, `docs/skills/ci-tooling.md` | Understand integration contracts, update cadence, and boundaries. |
| **End users assessing release trust** | `README.md`, `docs/MVP_1_0_READINESS.md`, `docs/skills/systemd-sysupdate-verification.md` | Learn what the project ships, how updates are signed, and how to verify artifacts. |

No audience gets its own silo. `README.md` and `AGENTS.md` are signposts; skills are the shared source of truth.

---

## 11. Verification of This Plan

Before this overhaul can be called done:

- [ ] All required files exist and are readable: `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, `docs/skills/INDEX.md`, `docs/skills/skill-improvement.md`.
- [ ] Every skill file has valid front-matter and no skill exceeds 500 lines.
- [ ] No `TODO/FIXME/draft` markers remain in `*.md` on `main`.
- [ ] Internal links in `docs/` are valid.
- [ ] `just validate` passes after any code-doc changes.
- [ ] `docs-checks` CI workflow passes on the final PR.

---

## 12. Sources Recap

- **Anthropic Skills** (`/anthropics/skills`, Context7) — SKILL.md front-matter validation, kebab-case naming, description budgets, three-level progressive loading, skill body budget (<500 lines), bundled resources.
- **Vercel Labs Skills** (`/vercel-labs/skills`, Context7) — skill discovery paths (`skills/`, `.agents/skills/`, etc.) and root index as entry point.
- **Toss Technical Writing** (`/toss/technical-writing`, Context7) — heading clarity, `INDEX.md` master navigation, hierarchical page structure.
- **Model Context Protocol spec** (modelcontextprotocol.io, fetched + indexed) — confirms MCP is a protocol specification, not a repository skill-file layout standard.
- **AAIF** — not found in Context7. This plan uses the widely adopted root `AGENTS.md` pattern and notes the gap explicitly.
