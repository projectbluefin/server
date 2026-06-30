# AGENTS.md

`fsdk-containers` brings **distroless patterns to [freedesktop-sdk](https://gitlab.com/freedesktop-sdk/freedesktop-sdk) (FSDK)**.
It is a [BuildStream 2](https://buildstream.build/) project. No Containerfiles for
the images themselves, no package managers in the output — BST elements that carve
runtime-only, slim-by-default OCI images out of FSDK `components/*`.

Load **[docs/skills/README.md](docs/skills/README.md)** for the skill routing table.
Only load the docs relevant to your task.

> **Before using any tool or library: look up its docs via Context7 first. Always.**
> BuildStream, oci-builder, podman, GitHub Actions, FSDK split-rules — every tool
> has live, authoritative docs. Pattern: `resolve-library-id` → `get-library-docs`
> → implement → cite the section. Guessing and trial-and-error are banned.

## What this repo is

- **Focus:** apply the distroless playbook (carve runtime, strip bloat, ship slim)
  to FSDK's already-patched components.
- **Inheritance, not reinvention:** images get FSDK's CVE patching and reproducible
  builds for free. We never maintain a separate package set.
- **Slim by default:** there is no "batteries" tier. The default image is the slim
  image. Keep only cheap crash-preventers (tzdata, common charsets, CA certs).
- **One documented exception — machine images.** A non-distroless lane exists for
  full dev-environment containers booted by `systemd-nspawn`/`machinectl` (e.g.
  `brew`): a rootfs `.tar.gz`, with shell/init/locale kept and the SLIM recipe NOT
  applied. This is deliberate and scoped — see
  [docs/skills/nspawn-machine-image.md](docs/skills/nspawn-machine-image.md). Do not
  generalise it to the OCI images.

## Hard rules

1. **Compose from `components/*`, never `platform.bst`.** `platform.bst` drags in
   Wayland/Mesa/PipeWire desktop bloat. Always target the minimum component set.
2. **No `x86_64_v3`.** This is a broad-compatibility baseline (diverges from dakota).
   Do not re-add the v3 micro-arch option.
3. **Don't duplicate upstream.** If a tool already ships an official, maintained
   CNCF/upstream distroless image (e.g. `kubectl`), consume that — do not rebuild
   it here. This is a contributor guideline, not the repo's headline; the headline
   is "distroless patterns for FSDK".
4. **Distroless means no shell.** The bash binary lives in the FSDK `runtime`
   domain, not the `shells` domain, so `compose exclude: shells` does NOT remove it.
   The SLIM recipe `rm`s it explicitly. Keep `just verify` green.

## Build / test commands (verified)

BuildStream runs inside the FSDK `bst2` container via the `just bst` wrapper —
nothing to install but `podman` + [`just`](https://github.com/casey/just).

```
just validate   # resolve the element graph (no build)
just build      # build + load ghcr.io/projectbluefin/base:latest
just verify     # 4 gates: no shell, CA certs, tzdata, slim-bloat-removed
just tags       # show FSDK-derived tags
```

`just verify` is the contract. All four gates must pass before merge.

## Versioning

The version axis is the **FSDK release**, parsed from the pinned junction ref in
`elements/freedesktop-sdk.bst`: `:latest` (rolling), `:25.08` (FSDK minor line),
`:25.08.13` (point release, immutable). Every image self-declares its base via
`io.projectbluefin.fsdk.version` and `io.projectbluefin.fsdk.ref` labels. Follow
the FSDK lifecycle — see [docs/skills/bump-fsdk-version.md](docs/skills/bump-fsdk-version.md).

## The self-improvement loop

Every session produces two outputs:

1. **The work** — the element, fix, or image.
2. **The learning** — what a future agent needs to know, written into `docs/skills/`.

Output 1 without Output 2 leaves the project no smarter. Before handoff, update or
add the relevant skill file. See [docs/skills/skill-improvement.md](docs/skills/skill-improvement.md).
