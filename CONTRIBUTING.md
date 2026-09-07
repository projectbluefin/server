# Contributing to Bluefin Server

Thanks for contributing. This repository is optimized for AI coding agents first; human contributors follow the same skill-driven workflow and conventions.

## Contributor workflow and rules

1. Read [`AGENTS.md`](AGENTS.md) and the skill in [`docs/skills/index.md`](docs/skills/index.md) matching your task.
2. AI agents must query the `projectbluefin` MCP server (`search_knowledge(query, limit)`, `get_factory_status()`, `get_work_queue()`) before investigating or implementing.
3. Make the smallest change that solves the problem.
4. Run `just validate` on every change that touches the element graph.
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

## References

- [`AGENTS.md`](AGENTS.md) — root entry point, hard rules, build matrix, and boundaries.
- [`docs/skills/index.md`](docs/skills/index.md) — lazy-load manifest routing to the appropriate skill.
- [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) — guide for creating or refining skills.

## License

By contributing, you agree that your contributions will be licensed under Apache-2.0.
