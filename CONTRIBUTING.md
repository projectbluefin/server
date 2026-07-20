# Contributing to Bluefin Server

Thanks for helping build Bluefin Server.

## Principles

- **Compose from FSDK `components/*`, never `platform.bst`.** Keep the OS image
  server-focused; do not pull in desktop stacks.
- **No `x86_64_v3`.** The base image must run on the broadest CPU baseline.
- **Use native systemd tooling.** Prefer `systemd-sysinstall`, `systemd-repart`,
  `bootctl`, and `ukify` over custom installers or shell scripts.
- **PARTUUID boot entries only.** Never hardcode block device paths such as
  `/dev/vda2` in boot configuration.
- **DDI-first.** The OS payload is an offline, compressed XFS DDI; updates are
  image replacements, not in-place package mutations.

## Prerequisites

- `podman`
- [`just`](https://github.com/casey/just)

BuildStream runs inside the FSDK `bst2` container via `just bst` — you do not
install BuildStream locally.

## Workflow

1. Read [`AGENTS.md`](AGENTS.md) and the relevant file in [`docs/skills/`](docs/skills/).
2. Make your change.
3. Validate the element graph:

   ```
   just validate
   ```

4. For installer/DDI changes, also verify with a local build or cluster build:

   ```
   just build-installer       # or just cluster-build
   ```

5. Update or add a `docs/skills/*.md` file capturing anything a future
   contributor would need to know (the self-improvement loop).

## Common tasks

| Task | Skill |
|---|---|
| Build or debug the DDI installer | [`docs/skills/ddi-installer.md`](docs/skills/ddi-installer.md) |
| Bump the FSDK version | [`docs/skills/bump-fsdk-version.md`](docs/skills/bump-fsdk-version.md) |
| Work on the k3s systemd-sysext | [`docs/skills/k3s-sysext.md`](docs/skills/k3s-sysext.md) |
| Write or debug CI workflows | [`docs/skills/ci-tooling.md`](docs/skills/ci-tooling.md) |
| Cut bloat / remove dependencies | [`docs/skills/avoid-over-engineering.md`](docs/skills/avoid-over-engineering.md) |

## Conventions

- BuildStream elements only. No Containerfiles.
- Commit messages: imperative mood, explain the **why**.
- All documentation changes are also verified against the source of truth
  (`Justfile`, `elements/`, `.github/workflows/build.yml`).

## License

By contributing you agree your work is licensed under [Apache-2.0](LICENSE).
