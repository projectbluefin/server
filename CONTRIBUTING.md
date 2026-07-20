# Contributing to Bluefin Server

Thanks for helping build Bluefin Server.

For the canonical project overview and contributor workflow, start with
[README.md](README.md). The root README is the main landing page for the
project, while this file is a short pointer for common contributor steps.

## Quick contributor checklist

1. Read [AGENTS.md](AGENTS.md) and the relevant skill in [docs/skills/](docs/skills/).
2. Make your change.
3. Validate the element graph:

   ```sh
   just validate
   ```

4. For installer or DDI changes, also run a local or cluster build:

   ```sh
   just build-installer       # or just cluster-build
   ```

5. Update or add a documentation skill when the change affects future workflow,
   build, or debug knowledge.

## Useful references

- [README.md](README.md) for the project overview and contributor workflow.
- [docs/skills/INDEX.md](docs/skills/INDEX.md) for the skill index.
- [docs/skills/ddi-installer.md](docs/skills/ddi-installer.md) and
  [docs/skills/ddi-installer-build.md](docs/skills/ddi-installer-build.md)
  for installer / DDI work.
- [docs/skills/k3s-sysext.md](docs/skills/k3s-sysext.md) and
  [docs/skills/k3s-sysext-ops.md](docs/skills/k3s-sysext-ops.md) for the k3s
  sysext.
- [docs/skills/ci-tooling.md](docs/skills/ci-tooling.md) for workflow
  conventions.

## License

By contributing you agree your work is licensed under [Apache-2.0](LICENSE).
