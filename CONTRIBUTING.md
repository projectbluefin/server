# Contributing to Bluefin Server

Thanks for contributing. This repository is optimized for AI coding agents first; human contributors follow the same skill-driven workflow and conventions.

## Contributor workflow and rules

1. Read [`AGENTS.md`](AGENTS.md) and the skill in [`docs/skills/index.md`](docs/skills/index.md) matching your task.
2. AI agents must query the `projectbluefin` MCP server (`search_knowledge(query, limit)`, `get_factory_status()`, `get_work_queue()`) before investigating or implementing.
3. Make the smallest change that solves the problem.
4. Run `just validate` on every change that touches the element graph.
   `just test-unit` runs pytest (install its plugins and `just lint-python`'s tools with `python3 -m pip install -r .github/requirements-ci.txt`) and bats; without a local `bats` it runs bats from a digest-pinned container through `podman`.
5. Validate documentation changes with `python3 .github/scripts/docs-checks.py`.
6. Use Conventional Commits (`feat:`, `fix:`, `docs:`, `ci:`, `chore:`).
7. Attribution trailers are required on all AI-assisted commits:
   ```text
   Assisted-by: <Model> via GitHub Copilot
   Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>
   ```
8. Staging audit: never use `git add -A` or `git add .`. Audit staged changes using `git status` and `git diff --cached --name-only`.
9. Remove any TODO or work-in-progress markers before opening a PR.
10. Target `main`. Keep branches local until ready; no WIP PRs.

## Review and merge

Pull requests merge through Prow (`.github/workflows/prow.yml`), not the merge button:

- An approver listed in [`OWNERS`](OWNERS) comments `/lgtm` and `/approve` (Prow accepts both only
  from accounts in `OWNERS`).
  With both `lgtm` and `approved` labels and passing checks, Prow adds the PR to the merge queue.
- Use `/hold` to block merging and `/hold cancel` to release it. Add a `/kind` label to classify the PR.
- `OWNERS` is generated from `projectbluefin/.project`'s `maintainers.yaml` by its `sync-owners.yml`
  workflow. Do not edit it here: change `maintainers.yaml` in `projectbluefin/.project`.
- See [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) ("Workflow Structure") for the Prow jobs.
- Who sets each label (Prow, the hive, Renovate or a person) and what reads it is in the "Labels" table of
  [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md).

## References

- [`AGENTS.md`](AGENTS.md) — root entry point, hard rules, build matrix, and boundaries.
- [`docs/skills/index.md`](docs/skills/index.md) — lazy-load manifest routing to the appropriate skill.
- [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) — guide for creating or refining skills.

## License

By contributing, you agree that your contributions will be licensed under Apache-2.0.
