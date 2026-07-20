# Contributing to Bluefin Server

Thanks for contributing. This repo is optimized for AI coding agents first; human contributors should follow the same skill-driven path.

## Quick contributor checklist

1. Read [`AGENTS.md`](AGENTS.md) and the skill in [`docs/skills/index.md`](docs/skills/index.md) that matches your change.
2. Make the smallest change that solves the problem.
3. Run `just validate` on every change that touches the element graph.
4. Update the skill that matches your change while the work is fresh.
5. Remove any `TODO/FIXME` or work-in-progress markers from docs before merging.
6. Use Conventional Commits for commits and PR titles (`feat:`, `fix:`, `docs:`, `ci:`, `chore(deps):`).
7. Target `main`. Keep branches local until ready; no WIP PRs.

## Useful references

- [`AGENTS.md`](AGENTS.md) — root entry point, hard rules, build commands, boundaries.
- [`docs/skills/index.md`](docs/skills/index.md) — lazy-load manifest that routes to the right skill.
- [`docs/skills/skill-improvement.md`](docs/skills/skill-improvement.md) — how to add or refactor skills.

## License

By contributing, you agree that your contributions will be licensed under Apache-2.0.
