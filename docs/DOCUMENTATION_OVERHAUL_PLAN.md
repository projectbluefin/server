# Bluefin Server — Agent-First Documentation Overhaul Plan

**Repository:** `/var/home/jorge/src/server` (`projectbluefin/server`)  
**Scope:** root `AGENTS.md`, human-facing docs (`README.md`, `CONTRIBUTING.md`), `docs/skills/`, and the CI doc-quality gate. Code changes are out of scope unless a doc requires a snippet to stay correct.

This plan is the executable artifact. It inventories the current docs, prescribes the target structure, defines lazy-loading and token-efficiency rules, drafts the canonical `AGENTS.md`, and gives a file-by-file cleanup sequence.

---

## 1. Research basis & sources

### Context7 queries run

1. `MCP skill authoring conventions front matter metadata docs/skills layout`
2. `model context protocol skill lazy loading minimal token usage`
3. `AAIF agents.md standard structure`
4. `skill improvement meta-skill documentation maintenance`
5. `progressive disclosure lazy loading context overload skills documentation index llms.txt`
6. `AGENTS.md boundaries root entry agent navigation`

### Sources consulted via Context7

| Library ID | Relevance | Key guidance used |
|---|---|---|
| `/websites/modelcontextprotocol` | High | MCP is a JSON-RPC protocol. The **Skills over MCP** working group covers skill representation, discovery, and consumption. **Primitive Grouping** recommends progressive disclosure when primitives exceed 1–5% of context. Agent skills are portable instruction sets. |
| `/llmstxt/modelcontextprotocol_io_llms_txt` | High | Use a lightweight documentation index (`llms.txt`) for discovery. **Progressive discovery** defers loading full tool/skill definitions via a `search_tools` meta-tool to save tokens. |
| `/llmstxt/modelcontextprotocol_io_llms-full_txt` | Medium | Skill packaging examples include a `SKILL.md` plus a `references/` folder for supporting material. Skills install into `~/.claude/skills/` or project-local `.agents/skills/`. |
| `/websites/agents_md` | High | `AGENTS.md` is a root Markdown file for AI coding agents; no required fields; nearest file in the tree wins; typical sections are project overview, build/test commands, style, boundaries. |
| `/agentsmd/agents.md` | High | Same as above; confirms `AGENTS.md` complements `README.md` and uses standard Markdown. |
| `/pskoett/self-improving-agent` | High | `SKILL.md` front-matter uses `name`, `description`, and `metadata`; includes promotion decision tree (behavioral → `SOUL.md`, workflow → `AGENTS.md`, tool/verified solution → skill); learning-entry format for captured patterns. |

### Standards gaps & tradeoffs

- **AAIF is not indexed in Context7.** The plan therefore uses the widely adopted `AGENTS.md` root-agent entry pattern as the AAIF-aligned convention and notes the gap explicitly.
- **MCP does not define repository skill-file layout.** The plan follows the Skills-over-MCP working-group direction plus the community pattern of one `SKILL.md` per skill in a `skills/` directory.
- **Token budgets.** No Context7 source gave exact token counts. The plan uses line budgets as a proxy because they are easy to enforce in CI and correlate strongly with context-window consumption.

---

## 2. Repository audit

Audit scope: all `*.md` files owned by this repository. Dependency caches under `.bst/staged-junctions/`, `.pytest_cache/`, and `node_modules/` are excluded.

| File | Lines | Classification | Notes / action |
|---|---|---|---|
| `AGENTS.md` | 72 | **Keep / polish** | Already matches the AAIF root-agent shape. Hard rules and boundaries are present; verification checklist includes the internal-only-hostname rule. |
| `README.md` | 42 | **Keep / polish** | Human/quick-start landing page. Trust signals, quick start, and links are present. Keep under 200 lines; canonical build matrix lives in `AGENTS.md`. |
| `CONTRIBUTING.md` | 23 | **Keep** | Short contributor path that defers to `AGENTS.md` and `docs/skills/index.md`. Could mention `docs-checks`, but otherwise fine. |
| `docs/MVP_1_0_READINESS.md` | 72 | **Keep / refresh** | Useful release-trust audit. Convert `Phase A/B/C/D` subheadings to a flat priority list and replace absolute downstream repo paths with generic cross-repo references. |
| `docs/DOCUMENTATION_OVERHAUL_PLAN.md` | 423 | **Replace** | This file is the new plan. |
| `docs/skills/index.md` | 45 | **Keep / refresh** | Lazy-load manifest is correct. Remove the `192.168.1.102:30500` internal IP from Standing facts; move workflow identifiers to a generic factory label; keep workflow names only if they are useful cross-repo pointers. |
| `docs/skills/skill-improvement.md` | 105 | **Keep / refresh** | Meta-skill is solid. Fix leftover uppercase `docs/skills/INDEX.md` references to match the actual lowercase filename. |
| `docs/skills/avoid-over-engineering.md` | 81 | **Keep / refresh** | Focused reference. Fix one uppercase `INDEX.md` reference. |
| `docs/skills/architecture-roadmap.md` | 37 | **Keep** | Stable roadmap stub; links to source-verified gaps. |
| `docs/skills/bump-fsdk-version.md` | 88 | **Keep** | Focused how-to with Renovate/GHA automation context. |
| `docs/skills/ci-tooling.md` | 134 | **Keep** | Covers SHA pinning, permissions, and workflow shape. No internal-only refs. |
| `docs/skills/ddi-installer-build.md` | 130 | **Keep / refresh** | Replace the `ghost` hostname with a generic `<build-cache-host>` placeholder so the doc is reusable outside the original lab. |
| `docs/skills/ddi-installer.md` | 170 | **Keep** | Architecture reference under the 300-line warning and 500-line hard cap. |
| `docs/skills/factory-integration.md` | 101 | **Keep / refresh** | Genericize the downstream workflow reference (“the factory CI repository” rather than a repo path + internal details). Keep the temporary SSH exception. |
| `docs/skills/gap-analysis-distros.md` | 196 | **Keep** | Source-verified comparison; under budget. Cross-links to roadmap. |
| `docs/skills/k3s-sysext.md` | 120 | **Keep** | How-to for building/sysext design. |
| `docs/skills/k3s-sysext-ops.md` | 119 | **Keep** | How-to for enabling/troubleshooting. Some overlap with `k3s-sysext.md` is intentional (build vs. ops); keep split. |
| `docs/skills/system-containers.md` | 102 | **Keep** | Focused system-container how-to. |
| `docs/skills/systemd-sysext-extensions.md` | 111 | **Keep** | Extension loading reference. |
| `docs/skills/systemd-sysupdate-verification.md` | 133 | **Keep** | Trust/signing reference. No internal-only refs. |
| `docs/skills/tpm2-credential-sealing.md` | 72 | **Keep** | Focused how-to; no TODO/FIXME flags. |
| `.pytest_cache/README.md` | 8 | **Delete** | Generated test cache; not source docs. |

### Stale / contradictory / internal-only content to remove

1. **Internal IP address** — `docs/skills/index.md` Standing facts lists `192.168.1.102:30500`. Remove and replace with a generic registry label or a placeholder.
2. **Internal hostname** — `docs/skills/ddi-installer-build.md` references `ghost` for the BuildStream cache tunnel. Replace with `<build-cache-host>` and an explicit note that operators must substitute their own host.
3. **Downstream repo paths used as internal locations** — `docs/skills/factory-integration.md` and `docs/MVP_1_0_READINESS.md` write `projectbluefin/lab/...` paths inline. Downstream repo names are acceptable as cross-repo pointers, but keep them as links, not as authoritative internal paths. Where no public link exists, genericize.
4. **Uppercase `INDEX.md` references** — `docs/skills/skill-improvement.md` and `docs/skills/avoid-over-engineering.md` refer to `docs/skills/INDEX.md`. The real file is lowercase `index.md`; fix the references.

---

## 3. Target structure

```text
projectbluefin/server
├── AGENTS.md                        # Root AAIF-aligned agent entry point (≤200 lines)
├── README.md                        # Human trust/quick-start (≤200 lines)
├── CONTRIBUTING.md                  # Contributor checklist (≤100 lines)
├── LICENSE                          # Existing license
│
├── docs/
│   ├── DOCUMENTATION_OVERHAUL_PLAN.md   # This plan
│   ├── MVP_1_0_READINESS.md             # Release-readiness audit (≤250 lines)
│   │
│   └── skills/
│       ├── index.md                 # Lazy-load manifest (≤150 lines)
│       ├── skill-improvement.md     # Meta-skill: maintain docs/skills/
│       │
│       ├── architecture-roadmap.md
│       ├── avoid-over-engineering.md
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
├── .github/
│   ├── scripts/
│   │   └── docs-checks.py           # Frontmatter, budget, stale-flag, link validator
│   └── workflows/
│       ├── build.yml                # Existing build/release pipeline
│       └── docs-checks.yml          # Doc-quality CI gate
```

### Rationale by top-level item

- **`AGENTS.md`** — Mandatory root agent entry point. Must load in one context read and route agents to `docs/skills/index.md`.
- **`README.md`** — Human landing page. Optimized for trust, quick start, and links. Defers build details to `AGENTS.md`.
- **`CONTRIBUTING.md`** — Human contributor path. Points to `AGENTS.md` and `docs/skills/index.md` so skill content is never duplicated.
- **`docs/skills/index.md`** — The only eagerly loaded skill file. It is the routing table and loading contract; keeping it small is the highest priority.
- **`docs/skills/skill-improvement.md`** — The meta-skill that documents the skill frontmatter schema, splitting rules, and verification steps.
- **`docs/DOCUMENTATION_OVERHAUL_PLAN.md`** — Living audit and execution record. Not a skill.
- **`docs/MVP_1_0_READINESS.md`** — External evaluator artifact. Not a skill; kept concise.
- **`.github/scripts/docs-checks.py`** — The enforcement layer for the rules in this plan.

---

## 4. Lazy-loading design for `docs/skills/`

### 4.1 Index / manifest (`docs/skills/index.md`)

`AGENTS.md` points to `docs/skills/index.md` as the next read. The index is the only skill file loaded eagerly. It contains:

1. A one-sentence purpose statement.
2. A routing table with one row per skill: filename, trigger, one-line scope.
3. The loading contract: read only the skill whose trigger matches the current task; follow cross-references only when the referenced topic is part of the task.

The index stays under the 150-line budget and its frontmatter description stays under 1024 characters.

### 4.2 Skill file naming & scoping

- File name = `name` metadata = kebab-case, lowercase alphanumerics and hyphens only, ≤64 characters.
- One skill per file.
- Split a skill when it exceeds 300 lines: move long reference material to `docs/skills/<parent>-reference.md`, keep the decision tree and links in the parent, and add the child to the index.
- No numbered prefixes; agents route by trigger words, not sort order.

### 4.3 Front-matter conventions

Every `docs/skills/*.md` file starts with:

```yaml
---
name: <kebab-case-name>
description: <≤ 1024 characters, says what this skill does and when to use it>
metadata:
  type: how-to | reference | meta-skill | index
  status: stable
  last_updated: "YYYY-MM-DD"
  context7-sources:        # optional, record only when source-verified external docs are used
    - /org/project
---
```

Rules:
- `name` must match the filename stem.
- `description` is a plain string under 1024 characters.
- No extra top-level keys; agent tags go inside `metadata`.
- `metadata.status: draft` is forbidden on `main`. Move unfinished work to issues.
- `context7-sources` is optional and records external libraries the skill relies on.

### 4.4 Cross-references without duplication

- Use one-line Markdown links: `See [factory-integration.md](factory-integration.md)`.
- Do not copy a fact into two files. If a fact must appear in a human-facing file, link to the canonical skill.
- Keep a short “Standing facts” section in `index.md` only for ultra-stable one-liners (version scheme, registry type). Anything longer belongs in a skill.

---

## 5. Token-usage optimization rules

These rules are enforced by `.github/scripts/docs-checks.py` and must be honored by authors.

| Rule | Budget / detail | Rationale |
|---|---|---|
| **Skill body line limit** | ≤300 lines preferred; absolute max 500 lines | Keeps a skill body cheap to load in one context read. |
| **Reference child files** | >300 lines must split into `<parent>-reference.md` | Long reference material loads only when needed. |
| **Index size** | ≤150 lines | Eagerly loaded; must stay small. |
| **Root `AGENTS.md`** | ≤200 lines | First doc loaded; should fit easily. |
| **Description length** | ≤1024 characters in frontmatter | Metadata is always in context. |
| **Heading hygiene** | Every heading must state a concrete action or topic | “Miscellaneous” headings waste context. |
| **Canonical source** | One doc per fact; all others link | Prevents drift and duplicated token spend. |
| **Link vs. inline** | Inline definitions only for terms defined in the current doc | Reduces cross-loading. |
| **Tables over prose** | Prefer tables for comparisons and checklists | Dense, scannable, cheap. |
| **No stale markers in docs** | Zero `TODO/FIXME/XXX/HACK/draft` on `main` | Stale flags poison search and agent decisions. |
| **Code snippets** | Keep minimal and copy-pasteable; point to repo files for full examples | Avoids long pasted config. |

---

## 6. `AGENTS.md` target contents

The existing `AGENTS.md` is already AAIF-aligned. The target content below keeps the current shape, with only minor wording consistency polish.

```markdown
# Bluefin Server — Agent Entry Point

Bluefin Server is an FSDK-based, image-based Linux server OS. It produces:
- an immutable XFS DDI OS payload (`oci/bluefin-server-ddi.bst`)
- an offline, systemd-native installer raw disk (`oci/bluefin-server-installer.bst`)
- an optional k3s `systemd-sysext` (`oci/k3s-sysext.bst`)

## What agents should know first

1. Read this file.
2. Load [`docs/skills/index.md`](docs/skills/index.md) to route to the skill for your task.
3. Never guess label names, workflow secrets, or infrastructure hostnames — check the relevant skill.

## Hard rules

1. Compose from FSDK `components/*`. Never use `platform.bst`.
2. Keep the CPU baseline broad: no `x86_64_v3`.
3. Installer must stay `systemd-sysinstall`-native; no custom installer scripts or non-native installers.
4. No shell in the running OS DDI image (temporary exception: SSH is enabled for bring-up and cluster boot tests; see [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md)).
5. Boot entries use GPT `PARTUUID`; never hardcode device paths.
6. One canonical source per fact; do not duplicate content across docs.

## Build / test commands

All `just` targets run BuildStream inside the FSDK `bst2` container via `just bst`; BuildStream is not installed locally.

| Command | Purpose |
|---|---|
| `just validate` | Merge-contract graph check — run this on every change. |
| `just build-ddi` | Local OS DDI payload build. |
| `just export-ddi` | Export DDI artifacts to `dist/ddi/`. |
| `just build-installer` | Local full installer build. |
| `just export-installer` | Export installer + UKI to `dist/`. |
| `just build-sysext` | Build the k3s `systemd-sysext`. |
| `just export-sysext` | Export sysext artifacts to `dist/sysext/`. |
| `just show-me-the-future` | Local QEMU installer smoke test. |

## Skill routing

| Task | Skill |
|---|---|
| Build or debug the installer / DDI | [`docs/skills/ddi-installer.md`](docs/skills/ddi-installer.md), [`docs/skills/ddi-installer-build.md`](docs/skills/ddi-installer-build.md) |
| Factory role, k3s sysext rationale, lab integration | [`docs/skills/factory-integration.md`](docs/skills/factory-integration.md) |
| Work with `systemd-sysext` / `systemd-confext` | [`docs/skills/systemd-sysext-extensions.md`](docs/skills/systemd-sysext-extensions.md) |
| Build or ship the k3s sysext | [`docs/skills/k3s-sysext.md`](docs/skills/k3s-sysext.md), [`docs/skills/k3s-sysext-ops.md`](docs/skills/k3s-sysext-ops.md) |
| Update the FSDK pin / versioning | [`docs/skills/bump-fsdk-version.md`](docs/skills/bump-fsdk-version.md) |
| CI workflows, action SHA pinning | [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) |
| Release signing / sysupdate trust | [`docs/skills/systemd-sysupdate-verification.md`](docs/skills/systemd-sysupdate-verification.md) |
| Credential sealing with TPM2 | [`docs/skills/tpm2-credential-sealing.md`](docs/skills/tpm2-credential-sealing.md) |
| System containers (`machinectl`) | [`docs/skills/system-containers.md`](docs/skills/system-containers.md) |
| Cut bloat / avoid over-engineering | [`docs/skills/avoid-over-engineering.md`](docs/skills/avoid-over-engineering.md) |
| Add or refactor skills | [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) |

## Documentation conventions

- Update only the skill that matches your change.
- Keep `AGENTS.md` small; do not list deep context here.
- Remove `TODO/FIXME` and work-in-progress markers before merging; move unfinished work to issues.
- Use Conventional Commits. For doc-only changes: `docs:`.

## Boundaries

- Do not add Containerfiles or shell-based installers.
- Do not hardcode block device paths in boot configuration.
- Do not put Kubernetes or debug tooling in the base DDI if it can live in a sysext or system container.
- Do not duplicate a fact already in a skill.

## Verification

- [ ] `just validate` passes.
- [ ] Any changed skill is listed in [`docs/skills/index.md`](docs/skills/index.md).
- [ ] No new internal-only hostnames or proprietary names appear in `AGENTS.md` or skills.
```

---

## 7. Cleanup execution plan

### Phase 1 — Remove internal-only references

1. Edit `docs/skills/index.md`: remove the IP address from Standing facts; rewrite the registry line as a generic label (e.g., “Factory OCI registry”). Keep workflow names only as cross-repo identifiers if they link to a public repo.
2. Edit `docs/skills/ddi-installer-build.md`: replace `ghost` with `<build-cache-host>` and add a note that the operator must set the host for their own cache tunnel.
3. Edit `docs/skills/factory-integration.md`: replace absolute downstream repo paths with generic “downstream factory CI repository” framing; keep deep links only if they are public, stable URLs.

### Phase 2 — Fix remaining consistency issues

4. Edit `docs/skills/skill-improvement.md`: change uppercase `docs/skills/INDEX.md` references to lowercase `docs/skills/index.md`.
5. Edit `docs/skills/avoid-over-engineering.md`: fix the one uppercase `docs/skills/INDEX.md` reference.
6. Edit `docs/MVP_1_0_READINESS.md`: flatten the `Phase A/B/C/D` subsections into a numbered priority list; replace file-path references with generic cross-repo references.

### Phase 3 — Remove generated artifact

7. Delete `.pytest_cache/README.md`.
8. Ensure `.pytest_cache/` is in `.gitignore` so it is not accidentally committed.

### Phase 4 — Replace this plan file

9. Overwrite `docs/DOCUMENTATION_OVERHAUL_PLAN.md` with this document.

### Phase 5 — Validate

10. Run `python .github/scripts/docs-checks.py`.
11. Run `actionlint .github/workflows/*.yml` to confirm no workflow syntax regressions.
12. Run `just validate` if any snippet change could affect the BuildStream graph.

### Path mapping

| Old path | Action | New path / note |
|---|---|---|
| `AGENTS.md` | Keep / no structural change | same path |
| `README.md` | Keep / no structural change | same path |
| `CONTRIBUTING.md` | Keep / optional expansion | same path |
| `docs/skills/index.md` | Refresh | same path; remove internal IP |
| `docs/skills/skill-improvement.md` | Refresh | same path; fix `INDEX.md` → `index.md` refs |
| `docs/skills/avoid-over-engineering.md` | Refresh | same path; fix `INDEX.md` → `index.md` ref |
| `docs/skills/ddi-installer-build.md` | Refresh | same path; replace `ghost` with placeholder |
| `docs/skills/factory-integration.md` | Refresh | same path; genericize downstream references |
| `docs/MVP_1_0_READINESS.md` | Refresh | same path; flatten phases |
| `docs/DOCUMENTATION_OVERHAUL_PLAN.md` | Replace | same path; this plan |
| `.pytest_cache/README.md` | Delete | generated file |

---

## 8. Maintenance model

### Ownership

- **`AGENTS.md`, `docs/skills/index.md`, and `docs/skills/skill-improvement.md`** are owned by the docs maintainer. Changes must be reviewed by a docs maintainer.
- **Domain skills** are owned by the same owner as the corresponding code domain (installer, sysext, CI, etc.).
- **`README.md` and `CONTRIBUTING.md`** are owned by the docs maintainer with community feedback.

### Review triggers

Review docs whenever:
- `AGENTS.md` or any `docs/skills/*.md` changes.
- A new skill is added, renamed, split, or deleted.
- Build/test commands or workflow names change.
- Hard rules or boundaries evolve.
- Internal-only hostnames, IPs, or proprietary names are found in a PR.

### CI checks

The existing `.github/workflows/docs-checks.yml` (using `.github/scripts/docs-checks.py`) already enforces the core rules:

| Check | Fail condition |
|---|---|
| Frontmatter schema | Missing `name` or `description`; unknown top-level/metadata keys; `name` not kebab-case or >64 chars; description >1024 chars; `name` ≠ filename stem. |
| Status on `main` | Any skill `metadata.status` other than `stable`. |
| Skill line budget | Any `docs/skills/*.md` >500 lines. |
| Long-reference warning | Any skill >300 lines is annotated. |
| Stale markers | `TODO/FIXME/XXX/HACK` in any doc on `main`. |
| Draft markers | `draft` in any doc on `main`, except approved planning docs. |
| Internal link validity | Broken relative Markdown links or missing `index.md` in linked directories. |
| Root doc budgets | `AGENTS.md` >200, `README.md` >200, `CONTRIBUTING.md` >100, `MVP_1_0_READINESS.md` >250. |

Optional enhancements for a later PR:
- Extend link validation to `docs/DOCUMENTATION_OVERHAUL_PLAN.md`.
- Validate `AGENTS.md` references only files that exist.
- Add a check that no new internal IP addresses or internal hostnames are introduced.

### Skill improvement meta-skill

`docs/skills/skill-improvement.md` is the canonical meta-skill. It must continue to document:
- When to create a new skill vs. a reference child file.
- The frontmatter schema and naming rules.
- How to add or remove a row in `docs/skills/index.md`.
- How to split a skill when it exceeds 300 lines.
- The verification steps: `docs-checks`, `just validate`, `actionlint`.
- The rule that a skill is updated **before** the handoff that touches its topic.

---

## 9. Audience mapping

| Audience | Primary docs | How the structure serves them |
|---|---|---|
| **External evaluators** (trust, release readiness) | `README.md`, `AGENTS.md`, `docs/MVP_1_0_READINESS.md`, `docs/skills/systemd-sysupdate-verification.md`, `docs/skills/ci-tooling.md` | Quick scan of process, build trust signals, verification checklists, and signing model. |
| **Active contributors / agents** | `AGENTS.md`, `docs/skills/index.md`, task-specific skills | Fast routing: agents load only the skill that matches the current task. |
| **Downstream maintainers** | `docs/skills/factory-integration.md`, `docs/skills/architecture-roadmap.md`, `docs/skills/ci-tooling.md` | Understand integration contracts, update cadence, and boundaries. |
| **End users assessing release trust** | `README.md`, `docs/MVP_1_0_READINESS.md`, `docs/skills/systemd-sysupdate-verification.md` | Learn what ships, how updates are signed, and how to verify artifacts. |

No audience gets its own silo. `README.md` and `AGENTS.md` are signposts; skills are the shared source of truth.

---

## 10. Verification of this overhaul

Before this overhaul can be considered complete:

- [ ] `AGENTS.md`, `README.md`, `CONTRIBUTING.md`, `docs/skills/index.md`, and `docs/skills/skill-improvement.md` exist and pass `docs-checks`.
- [ ] Every skill file has valid frontmatter, `metadata.status: stable`, and no skill exceeds 500 lines.
- [ ] No `TODO/FIXME/XXX/HACK/draft` markers remain in `*.md` on `main`.
- [ ] No internal IP addresses or internal hostnames remain in docs.
- [ ] Internal Markdown links in the changed docs resolve.
- [ ] `python .github/scripts/docs-checks.py` passes.
- [ ] `actionlint .github/workflows/*.yml` passes.
- [ ] `just validate` passes after any code-relevant doc change.
