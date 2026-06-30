# Contributing to fsdk-containers

Thanks for helping bring distroless patterns to freedesktop-sdk containers.

## Principles

- **Inherit, don't reinvent.** Images are carved from FSDK `components/*`. We rely
  on FSDK for the hard stuff (C libraries, language runtimes) and its CVE patching.
- **Slim by default.** The default image is the slim image. No "batteries" tier.
- **Keep the crash-preventers.** `tzdata`, a common charset set, and CA certificates
  stay — they cost little and prevent runtime crashes (`zoneinfo`, TLS, legacy decode).
- **Don't duplicate upstream.** If a tool already ships an official, maintained
  CNCF/upstream distroless image (e.g. `kubectl`), consume it. Don't rebuild it here.

## Prerequisites

- `podman` (rootless works)
- [`just`](https://github.com/casey/just)

BuildStream itself runs inside the FSDK `bst2` container via `just bst` — you do
not install BuildStream locally.

## Workflow

1. Read [AGENTS.md](AGENTS.md) and the relevant file in [docs/skills/](docs/skills/).
2. Make your change (see the skills for the common tasks below).
3. Run the contract:

   ```
   just validate   # graph resolves
   just build      # builds + loads the image
   just verify     # 4 gates must pass
   ```

4. Update or add a `docs/skills/*.md` file capturing anything a future contributor
   would need to know (the self-improvement loop).

## Common tasks

| Task | Skill |
| ---- | ----- |
| Add a new distroless image | [docs/skills/add-new-image.md](docs/skills/add-new-image.md) |
| Apply / extend the SLIM recipe | [docs/skills/slim-an-image.md](docs/skills/slim-an-image.md) |
| Bump the FSDK version | [docs/skills/bump-fsdk-version.md](docs/skills/bump-fsdk-version.md) |
| Verify distroless guarantees | [docs/skills/verify-distroless.md](docs/skills/verify-distroless.md) |

## Conventions

- BST elements only for image content. No Containerfile package overlays.
- Compose from `components/*`, never `platform.bst`.
- No `x86_64_v3` micro-arch.
- Commit messages: imperative mood, explain the *why*.

## License

By contributing you agree your work is licensed under [Apache-2.0](LICENSE).
