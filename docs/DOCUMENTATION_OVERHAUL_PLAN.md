# Documentation Overhaul Plan — Bluefin Server

> Artifact type: plan (BMAD Decision + Action document).
>
> Scope: overhaul every agent-facing documentation file in this repository so AI
> agents can discover, load, and act on it with minimal token usage. Human
> readability is a by-product; agent-first structure is the goal.
>
> Status: plan ready for execution. Source standards are cited in §2.

---

## 1. Executive Summary

This repository already has a usable `docs/skills/` skill set and a short
`AGENTS.md`. The overhaul makes three changes:

1. **Standardize on AAIF `AGENTS.md`** (root entry point, no proprietary
   extensions).
2. **Turn `docs/skills/` into a lazy-load skill library** with a tiny index,
   consistent front matter, cross-references, and strict size/duplication rules.
3. **Genericize prose** so downstream maintainers, external evaluators, and end
   users can read it without learning internal codenames, while preserving every
   actionable command and file path.

Execution is file-by-file; no new tooling is required beyond a Markdown linter
and a small schema checker (both can be added to CI later).

---

## 2. Standards Consulted

| Standard | Source | What it says (relevant to this plan) |
|----------|--------|--------------------------------------|
| **AAIF `AGENTS.md`** | `https://agents.md/` | `AGENTS.md` is a repo-root Markdown file for AI coding agents. No required fields. Reccommended coverage: overview, build/test commands, style, testing, security. Large monorepos may nest additional `AGENTS.md` files by package. |
| **MCP Specification 2025-03-26** | `https://modelcontextprotocol.io/specification/2025-03-26` | MCP standardizes the protocol between AI applications and external systems (tools, resources, prompts). It does **not** standardize repo-level `docs/skills/` layout; that convention comes from the broader agent-tooling community. |
| **MCP documentation index** | `https://modelcontextprotocol.io/llms.txt` | Confirms `/llms.txt` as an LLM-oriented documentation index. We mirror the idea with the `docs/skills/INDEX.md` manifest. |
| **OpenAI `codex` `AGENTS.md`** | `https://raw.githubusercontent.com/openai/codex/main/AGENTS.md` | Concrete example of an effective agent file: concise project framing, explicit `just` / `cargo` commands, file-size boundaries, and per-area routing. |

**Note on Context7:** The local toolset does not expose a Context7 MCP server, so
`resolve-library-id` / `query-docs` could not be run. The fallback sources above
are the public specifications the Context7 searches would have returned. Any
convention below that is not covered by those sources is marked **UNVERIFIED**
and justified by widely adopted community practice.

---

## 3. Repository Audit

Existing docs inventory and classification.

| File | Lines | Class | Rationale |
|------|-------|-------|-----------|
| `README.md` | 124 | **rewrite** | Contains useful public-facing copy but mixes human onboarding with agent commands. The agent-critical material (build commands, constraints, factory role) should be moved/cross-referenced from `AGENTS.md` and `docs/skills/`, while the README focuses on release trust and quick-start for humans. |
| `CONTRIBUTING.md` | 64 | **keep / minor rewrite** | Already concise and correct. Update it to point to `AGENTS.md` instead of duplicating build commands, and reference `docs/skills/INDEX.md` for task routing. |
| `AGENTS.md` | 80 | **rewrite** | Current file is good but is not structured as an AAIF entry point. Rewrite per AAIF guidance, add explicit “load this skill next” routing, and remove internal-only references. |
| `docs/skills/INDEX.md` | 57 | **keep / refine** | Already acts as the lazy-load manifest. Add a `skills:` manifest block in front matter so agents can parse it without reading the prose. Reduce embedded duplication. |
| `docs/skills/factory-integration.md` | 126 | **rewrite** | Stale/internal framing: uses `projectbluejin/lab`, `ghost`/`exo-1`, and product names. The architecture facts are canonical; genericize the framing and keep the comparison table. |
| `docs/skills/ddi-installer.md` | 393 | **rewrite** | The canonical installer reference, but too large for one skill chunk. Split into a parent skill plus child sections, or add an in-file `toc`/`skip-to` metadata block so agents can load only the relevant heading cluster. Remove duplicated build commands once they live in `AGENTS.md`. |
| `docs/skills/tpm2-credential-sealing.md` | 67 | **keep** | Sized and scoped correctly; just harmonize front matter. |
| `docs/skills/systemd-sysext-extensions.md` | 107 | **keep** | Good shape; add canonical cross-references to `k3s-sysext.md`. |
| `docs/skills/system-containers.md` | 104 | **keep** | Good shape; verify it does not duplicate `README.md` system-container section. |
| `docs/skills/skill-improvement.md` | 48 | **keep** | Becomes the meta-skill for adding and refactoring skills. Add a short schema definition and a “how to add a skill” checklist. |
| `docs/skills/gap-analysis-architecture.md` | 100 | **merge / rewrite** | Mixes implemented facts with future roadmap. Split: move verified design rules into the appropriate skills (`systemd-sysupdate-verification.md`, `tpm2-credential-sealing.md`, `systemd-sysext-extensions.md`), and move the remaining roadmap into a new `docs/skills/architecture-roadmap.md` (clearly marked `status: draft`). |
| `docs/skills/ci-tooling.md` | 136 | **keep / trim** | Remove duplicated `just` commands once `AGENTS.md` owns them; keep CI-specific conventions and SHA-pinning rules. |
| `docs/skills/bump-fsdk-version.md` | 93 | **keep / trim** | Remove the “Dakota” sibling-project note (internal-specific) or reframe it as generic guidance about stripping unused junction overrides. Keep the Renovate/GHA workflow facts. |
| `docs/skills/k3s-sysext.md` | 276 | **rewrite** | Second-longest skill. Keep architecture and build facts; pull the verbose runtime-testing sections into a collapsed “reference” block or child file so the main skill stays under 200 lines. Add cross-links to `systemd-sysext-extensions.md`. |
| `docs/skills/systemd-sysupdate-verification.md` | 131 | **keep / trim** | Canonical; reduce duplication with `ddi-installer.md` release section and `k3s-sysext.md` release section by linking to this file as the single source of truth for OTA signing. |
| `docs/skills/avoid-over-engineering.md` | 84 | **keep** | Already concise; add cross-links to the skill-improvement meta-skill. |

**Files to delete:** none. No file is fully obsolete; stale content is inside
otherwise-good files and should be edited in place.

---

## 4. Target Structure

```text
REPO ROOT
├── AGENTS.md                       # AAIF entry point (agent-first, 100–150 lines)
├── README.md                       # Human-facing quick-start + trust signals
├── CONTRIBUTING.md                 # Human contributor guide; links to AGENTS.md
├── LICENSE                         # unchanged
├── docs/
│   ├── INDEX.md                    # (optional) high-level map for humans browsing docs/
│   ├── DOCUMENTATION_OVERHAUL_PLAN.md  # this file
│   └── skills/
│       ├── INDEX.md                # lazy-load manifest (<= 100 lines + YAML front matter)
│       ├── skill-improvement.md    # meta-skill: how to add/refactor skills
│       ├── architecture-roadmap.md # formerly gap-analysis; status:draft roadmap only
│       ├── avoid-over-engineering.md
│       ├── bump-fsdk-version.md
│       ├── ci-tooling.md
│       ├── ddi-installer.md        # trimmed; child anchors if needed
│       ├── factory-integration.md  # genericized
│       ├── k3s-sysext.md           # trimmed
│       ├── systemd-sysupdate-verification.md
│       ├── systemd-sysext-extensions.md
│       ├── system-containers.md
│       └── tpm2-credential-sealing.md
```

Rationale for top-level files:

- `AGENTS.md`: Required by AAIF; the only file an agent is guaranteed to load
  first. Keep it self-contained for bootstrap; every non-trivial detail links to
  `docs/skills/`.
- `README.md`: Human-first, but mirrors `AGENTS.md` hard rules and links to the
  skill index so agents can also use it safely.
- `CONTRIBUTING.md`: Human workflow. Must not duplicate commands that live in
  `AGENTS.md`.
- `docs/skills/INDEX.md`: Machine-readable routing table with front-matter
  manifest and human-readable fast path.
- `docs/skills/skill-improvement.md`: The meta-skill that prevents documentation
  rot by making every session output “work + learning.”

**UNVERIFIED convention:** The `docs/skills/` directory name and the use of
root `AGENTS.md` are community conventions, not MCP spec requirements. The MCP
spec defines the protocol wire format; it does not constrain how a repository
organizes agent guidance.

---

## 5. Lazy-Loading Design for `docs/skills/`

### 5.1 Index / manifest

`docs/skills/INDEX.md` is the first skill file an agent loads after `AGENTS.md`.
It must be cheap to parse: small YAML front matter plus a routing table.

Front matter schema:

```yaml
---
name: skills-index
version: "2.0"
last_updated: "YYYY-MM-DD"
tags: [skills, routing, index]
description: |
  Short one-line purpose. No more than 25 words.
metadata:
  type: index
skills:
  - id: ddi-installer
    file: ddi-installer.md
    trigger: ["installer", "ddi", "systemd-sysinstall", "systemd-repart"]
    description: Build and debug the live installer media.
  - id: factory-integration
    file: factory-integration.md
    trigger: ["factory", "k3s sysext", "dowstream", "lab"]
    description: Server OS role inside the larger CI/OS factory.
  # ... etc.
---
```

Rules:

- The `skills:` array is the machine-readable source of truth. The Markdown
  table below it is for humans and may be generated from the YAML.
- Each skill has one primary `trigger` list. Use lower-case, comma-separated
  keywords an agent will find in user prompts.
- No skill description over 20 words.
- The index file stays **under 100 lines** total.

### 5.2 Skill file naming and scoping

- File name = kebab-case topic verb/noun. One skill per file.
- Scope = one concern. If a skill exceeds 200 lines, split it:
  - primary skill file keeps the “When to Use / When NOT / Core Process / Key
    Constraints / Verification.”
  - child file named `<skill>-reference.md` holds deep examples, manual test
    procedures, or copy-paste command dumps.
- Cross-reference, never duplicate. Example: `ddi-installer.md` links to
  `systemd-sysupdate-verification.md` for release signing; it does not restate
  the signing procedure.

### 5.3 Front-matter conventions

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
  (`reference`), judgment aid (`guide`), or future design (`design-roadmap`).
- `status`: `draft` for `architecture-roadmap.md` only.
- `context7-sources`: optional list of Context7 library IDs. Agents should
  resolve these before implementing tool-specific changes.
- `depends_on`: skills that should be loaded before this one. The agent loader
  follows dependencies depth-first and deduplicates.

### 5.4 Cross-references without duplication

Use one of two patterns:

1. **Inline see-also link** (for a related skill):
   `See [systemd-sysupdate-verification.md](systemd-sysupdate-verification.md).`
2. **Canonical fact block** (for a rule repeated in several skills):
   State the fact once in the most authoritative skill and in other skills
   write:
   `> Canonical rule: [Avoid forwarding Justfile recipes](avoid-over-engineering.md#forwarding-recipes).`

Never copy tables, command lists, or diagrams into more than one file. If a
fact needs to appear in two places, add a link.

---

## 6. Token-Usage Optimization Rules

Authors must follow these rules. CI can enforce them later.

| Rule | Rationale | Enforcement |
|------|-----------|-------------|
| **Heading hygiene** | Use `##` for top-level sections only when needed; prefer `###` for sub-sections so the file outline is shallow and agents can prune branches. | `markdownlint` + grep count of `^##` |
| **Section budget** | One skill = one concern. Main skill file ≤ 200 lines; child reference ≤ 300 lines. | CI line-count check |
| **Link vs. inline** | If the same prose would be useful in >1 skill, write it once and link. Exception: `AGENTS.md` may repeat the 5 hard rules because it is the bootstrap file. | Manual review + link-validity checker |
| **Single source of truth** | Build commands live in `AGENTS.md`. Release signing lives in `systemd-sysupdate-verification.md`. Factory role lives in `factory-integration.md`. | Grep-based structure checks |
| **Front-matter first** | Agents parse YAML metadata before reading prose. Keep front matter dense and accurate; do not put long essays in it. | YAML schema lint |
| **Bullet/table preference** | Use tables and bullets over paragraphs. They compress better and chunk cleanly. | None (manual) |
| **No “wall of context” intros** | Delete sentences that only say what the file is about. The front matter and first heading already do that. | Manual review |
| **Code blocks over inline lists** | Commands go in fenced blocks with language tag so agents can extract them mechanically. | `markdownlint` |
| **Avoid pronouns with ambiguous antecedents** | Bad: “it handles updates.” Good: “`systemd-sysupdate` handles updates.” | Manual review / text lint |

**UNVERIFIED convention:** The 200-line skill budget and the front-matter schema
are not AAIF/MCP requirements. They are derived from the common agent-tooling
pattern of keeping each loaded context window small and explicit
(openai/codex `AGENTS.md` enforces similar 500-line change limits; we apply the
same discipline to documentation files).

---

## 7. `AGENTS.md` Draft Contents

`AGENTS.md` is an AAIF-standard Markdown file. No required schema. This draft
is sized to be read in one agent context window.

```markdown
# Bluefin Server — Agent Entry Point

Bluefin Server is a BuildStream 2-based, image-based Linux server OS.
Load **[docs/skills/INDEX.md](docs/skills/INDEX.md)** to route to the skill
for your task.

## What this repo is

- **Core OS:** `oci/bluefin-server-ddi.bst` produces the immutable XFS DDI
  payload.
- **Installer media:** `oci/bluefin-server-installer.bst` produces a UEFI
  bootable raw GPT image with the DDI embedded as a data partition.
- **Interactive installer:** `systemd-sysinstall` (systemd 261+) on
  `/dev/console`; partitioning by `systemd-repart`.
- **Updates:** image-based A/B updates via `systemd-sysupdate` from GitHub
  Releases, verified with GPG-signed `SHA256SUMS` manifests.
- **Extensions:** optional layers are `systemd-sysext` (or `systemd-confext`)
  images, not packages baked into the base DDI.
- **Factory floor:** this OS is designed to be the base image for downstream
  CI labs and OS factories that build and test image-based Linux workloads.

## Hard rules

1. Compose from FSDK `components/*`. Never use `platform.bst`.
2. Keep the CPU baseline broad: no `x86_64_v3`.
3. Installer must stay `systemd-sysinstall`-native; no custom installer
   scripts or knuckle.
4. No shell in the running OS DDI image.
5. Boot entries use GPT `PARTUUID`; never hardcode device paths.

## Build / test commands

BuildStream runs inside the FSDK `bst2` container via the `just bst` wrapper.
Only `podman` and `just` are required locally.

```bash
just validate              # merge contract: resolve the element graph
just tags                  # show derived FSDK versions
just build-installer       # local full installer build
just export-installer      # export .raw.zst + SHA256SUMS
just build-ddi             # local OS DDI payload build
just export-ddi            # export DDI + SHA256SUMS
just build-sysext          # build k3s systemd-sysext
just export-sysext         # export sysext artifacts
just cluster-build         # submit build to the CI cluster (preferred)
just show-me-the-future    # QEMU smoke test of the installer
```

## Skill routing

| Task | Load |
|------|------|
| Build or debug the installer / DDI | `docs/skills/ddi-installer.md` |
| Factory role, k3s sysext rationale | `docs/skills/factory-integration.md` |
| Work with systemd-sysext / confext | `docs/skills/systemd-sysext-extensions.md` |
| Build or ship the k3s sysext | `docs/skills/k3s-sysext.md` |
| Update the FSDK pin / versioning | `docs/skills/bump-fsdk-version.md` |
| CI workflows, action SHA pinning | `docs/skills/ci-tooling.md` |
| Release signing / sysupdate trust | `docs/skills/systemd-sysupdate-verification.md` |
| Credential sealing with TPM2 | `docs/skills/tpm2-credential-sealing.md` |
| System containers (machinectl) | `docs/skills/system-containers.md` |
| Cut bloat / avoid over-engineering | `docs/skills/avoid-over-engineering.md` |
| Add or refactor skills or this file | `docs/skills/skill-improvement.md` |

## Documentation conventions

- Keep `AGENTS.md` small. For task-specific guidance, load the skill from
  `docs/skills/INDEX.md` rather than asking here.
- Update the skill that matches your work before handoff. Output = work +
  learning (see `docs/skills/skill-improvement.md`).
- Before using an external tool, prefer Context7 lookup for authoritative docs.
  If Context7 is unavailable, fetch the public spec and label uncertainty.

## Boundaries

- **Do not** add Containerfiles or shell-based installers.
- **Do not** hardcode block device paths in boot configuration.
- **Do not** put Kubernetes or debug tooling in the base DDI if it can live in
  a sysext or system container.
- **Do not** duplicate a fact that already lives in a skill file.

## Verification

- [ ] `just validate` passes before any handoff.
- [ ] Any changed skill file is listed in `docs/skills/INDEX.md`.
- [ ] Internal-only references (hostnames, private infra names) are not added to
      `AGENTS.md` or skill files.
```

---

## 8. Cleanup Execution Plan

Execute in this order so links never point into the void during the migration.

### Phase 1 — Bootstrap the new entry point

1. Rewrite `AGENTS.md` using the draft in §7.
2. Update `docs/skills/INDEX.md` to the manifest schema in §5.1.
3. Add `docs/skills/skill-improvement.md` additions: schema definition,
   “add a skill” checklist, and link to the lazy-loading rules.

### Phase 2 — Genericize internal framing

4. Rewrite `docs/skills/factory-integration.md`: replace `projectbluefin/lab`,
   `ghost`, `exo-1`, and similar internal names with generic language
   (“downstream CI lab,” “the OS factory”). Keep all architecture facts and
   tables.
5. Trim `docs/skills/bump-fsdk-version.md`: remove/reframe the “Dakota” note;
   keep the technical guidance on stripping unused junction overrides.
6. Split `docs/skills/gap-analysis-architecture.md`:
   - Move verified design rules to the canonical skills
     (`systemd-sysupdate-verification.md`, `tpm2-credential-sealing.md`,
     `systemd-sysext-extensions.md`).
   - Create `docs/skills/architecture-roadmap.md` with only the remaining
     roadmap; mark `status: draft` in front matter.

### Phase 3 — Chunk oversized skills

7. Rewrite `docs/skills/ddi-installer.md` to stay under 200 lines. Move the
   lengthy copy-paste examples and manual test procedures to a child file
   `docs/skills/ddi-installer-reference.md`.
8. Rewrite `docs/skills/k3s-sysext.md` similarly; move runtime testing recipes
   to `docs/skills/k3s-sysext-reference.md`.

### Phase 4 — Deduplicate and cross-link

9. Remove duplicated build-command tables from `README.md`,
   `CONTRIBUTING.md`, `ddi-installer.md`, `k3s-sysext.md`, and
   `ci-tooling.md`. Link to `AGENTS.md` for the canonical table.
10. Centralize release/signing facts in
    `systemd-sysupdate-verification.md`; replace the duplicate release
    sections in `ddi-installer.md` and `k3s-sysext.md` with one-line links.

### Phase 5 — Human docs refresh

11. Rewrite `README.md`: human-first quick-start, trust signals (signed
    releases, immutable tags), and links to `AGENTS.md` / skill index.
12. Rewrite `CONTRIBUTING.md`: remove duplicate commands; reference
    `AGENTS.md` and `docs/skills/INDEX.md`.

### Phase 6 — Validate

13. Run `just validate` to make sure no real code is broken.
14. Run a link check (e.g., `markdown-link-check` or a small shell script that
    lists all `[...](path)` targets and confirms they exist).
15. Run line-count checks (index ≤ 100 lines, main skills ≤ 200 lines,
    reference skills ≤ 300 lines, AGENTS.md ≤ 150 lines).

### Path mapping

| Old path | New path / action |
|----------|-----------------|
| `AGENTS.md` | rewritten in place (keep path) |
| `README.md` | rewritten in place |
| `CONTRIBUTING.md` | rewritten in place |
| `docs/skills/INDEX.md` | rewritten in place |
| `docs/skills/skill-improvement.md` | expanded in place |
| `docs/skills/factory-integration.md` | rewritten in place |
| `docs/skills/bump-fsdk-version.md` | trimmed in place |
| `docs/skills/gap-analysis-architecture.md` | split into `architecture-roadmap.md` + updates to other skills |
| `docs/skills/ddi-installer.md` | trimmed in place; deep reference moved to `docs/skills/ddi-installer-reference.md` |
| `docs/skills/k3s-sysext.md` | trimmed in place; deep reference moved to `docs/skills/k3s-sysext-reference.md` |
| `docs/skills/systemd-sysupdate-verification.md` | becomes canonical signing reference (small updates) |
| `docs/skills/tpm2-credential-sealing.md` | minor front-matter only |
| `docs/skills/systemd-sysext-extensions.md` | minor cross-links only |
| `docs/skills/system-containers.md` | minor cross-links only |
| `docs/skills/avoid-over-engineering.md` | minor cross-links only |
| `docs/skills/ci-tooling.md` | trim duplicated commands |
| `docs/DOCUMENTATION_OVERHAUL_PLAN.md` | this file (kept as record) |

---

## 9. Maintenance Model

### Ownership

- `AGENTS.md`: every agent edits it when a hard rule or bootstrap command
  changes.
- `docs/skills/INDEX.md`: updated whenever a skill file is added, removed, or
  renamed.
- Individual `docs/skills/*.md`: updated by the agent working on that topic
  (the skill-improvement loop).
- `README.md` / `CONTRIBUTING.md`: human contributors and release managers.

### Review triggers

Review a doc when any of these happen:

- A build/test command changes.
- A hard rule is added, removed, or weakened.
- A new skill is added or an existing skill is split.
- Internal-only names or URLs leak into docs.
- The `last_updated` front matter is older than 90 days (stale-digest flag).

### CI checks

| Check | Tool | Failure mode |
|-------|------|--------------|
| Markdown syntax | `markdownlint-cli` | Block PR merge. |
| Internal links | custom shell script or `markdown-link-check` | Block PR merge if a relative link is dead. |
| Front-matter schema | `yq`/Python validator against §5.3 schema | Block PR merge. |
| Line-count budgets | `wc -l` against §6 budgets | Warn; fail on PRs that grow files past 1.5x budget. |
| Proprietary reference scan | `grep -iE '(ghost|exo-1|dakota|internal.vpn|corp)' -- docs/ AGENTS.md README.md CONTRIBUTING.md` | Block PR merge if any match is not explicitly approved. |

### Skill improvement meta-skill

`docs/skills/skill-improvement.md` is the place where “how to maintain this
skill library” is documented. It must include:

- The front-matter schema (§5.3).
- The lazy-loading contract: index → skill file(s) → dependencies.
- The no-duplication rule and cross-reference patterns.
- A checklist for adding a new skill:
  1. Pick a file name matching the topic.
  2. Add front matter per schema.
  3. Add an entry to `docs/skills/INDEX.md`.
  4. Link from the relevant human docs (`README.md`, `CONTRIBUTING.md`,
     related skills).
  5. Run link and line-count checks.
- A checklist for refactoring a skill:
  1. Identify the canonical file for the fact.
  2. Move the fact; leave a forward link.
  3. Update the index if files are renamed or split.
  4. Update `last_updated`.

---

## 10. Audience Mapping

| Audience | Where they look | What they get |
|----------|-----------------|---------------|
| **External evaluators** (trust, process rigor) | `README.md`, `AGENTS.md`, signed-release workflow pointers in `systemd-sysupdate-verification.md` | Release trust signals, reproducible build commands, immutable versioning. |
| **Active contributors / agents** | `AGENTS.md` → `docs/skills/INDEX.md` → specific skill | Exact commands, hard rules, context7 tools to look up, and boundaries. |
| **Downstream maintainers** | `factory-integration.md`, `systemd-sysext-extensions.md`, `k3s-sysext.md` | How the OS composes into a larger factory and how to add extensions without forking the base DDI. |
| **End users assessing release trust** | `README.md`, `CONTRIBUTING.md`, `systemd-sysupdate-verification.md` | How updates are signed, where artifacts live, and the update/rollback model. |

There are no audience-specific silos. All content lives in one tree; headings
and the front-matter `type` field make it routable.

---

## 11. Verification of This Plan

Non-exhaustive checks an executor should run before calling the overhaul done:

```bash
# All required files exist and are readable
ls AGENTS.md README.md CONTRIBUTING.md docs/skills/INDEX.md docs/skills/skill-improvement.md

# No skill file has grown past the reference budget (child files get 300 lines)
awk 'NR==FNR{a[$1]=1;next} {print $1, $0}' <(find docs/skills -name '*.md') <(wc -l docs/skills/*.md)

# Build contract still holds
just validate
```

---

## Sources Recap

- AAIF `AGENTS.md` standard: `https://agents.md/`
- MCP Specification 2025-03-26: `https://modelcontextprotocol.io/specification/2025-03-26`
- MCP docs index (`llms.txt` pattern): `https://modelcontextprotocol.io/llms.txt`
- OpenAI `codex` agent file example: `https://raw.githubusercontent.com/openai/codex/main/AGENTS.md`

Context7 MCP was not available in this session, so the above public documents
were fetched directly and cited instead.
