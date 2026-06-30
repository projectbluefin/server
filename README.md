# fsdk-containers

**Bringing distroless patterns to [freedesktop-sdk](https://gitlab.com/freedesktop-sdk/freedesktop-sdk) (FSDK) containers.**

FSDK already maintains beautifully patched, reproducible builds of glibc and
every major runtime. This repo applies the distroless playbook to them — carve
out only the runtime, strip the bloat, ship slim by default — so you get a free,
OSS distroless suite that **inherits FSDK's CVE patching** instead of maintaining
a separate package set.

These containers are maintained for projectblufin/fsdk usage for cluster ops, etc. Digital sovereignty isn't just for nations, this controls our supply chain. 

## Images

| Image | Size | Description |
| ----- | ---- | ----------- |
| `ghcr.io/projectbluefin/base` | ~40 MB | Distroless base: glibc, coreutils, CA certificates, timezone data. No shell, no package manager. Multi-arch: linux/amd64, linux/arm64. |

### Machine images (not distroless)

| Image | Size | Description |
| ----- | ---- | ----------- |
| `ghcr.io/projectbluefin/brew` | ~410 MB | Homebrew developer environment as a **systemd-nspawn machine image** (a `.tar.zst` rootfs for `machinectl import-tar`, **not** an OCI image). Full dev env: bash, ruby, git, curl, gcc, patchelf, systemd init + the linuxbrew prefix. The distroless/slim rules do **not** apply here — see [docs/skills/nspawn-machine-image.md](docs/skills/nspawn-machine-image.md). Built with `just export-brew`. |

## How it works

Each image is composed from raw FSDK `components/*` (never `platform.bst`),
then chiseled with a BuildStream `compose` element that drops every non-runtime
split-rule domain, and finally run through the **SLIM recipe** in the OCI script
step. The slim recipe removes the large runtime-domain bloat that has no FSDK
domain to exclude it: shell binaries, `terminfo`, gcc sanitizer/fortran runtimes,
the `gconv` charset long-tail, the glibc `locale-archive`, and leaked build tools.

It deliberately **keeps** the cheap crash-preventers — `tzdata`, a common charset
set, CA certificates — so `datetime`/TLS work out of the box without the wheel
gymnastics other distroless suites push onto you.

Pipeline: `stack` (deps) -> `compose` (chisel) -> `script` (slim + oci-builder).
See [`docs/skills/slim-an-image.md`](docs/skills/slim-an-image.md) for the recipe.

## Versioning

There is no application version for a base image, so the version axis is the
FSDK release. Tags are derived from the pinned junction ref in
`elements/freedesktop-sdk.bst`:

- `:latest` -- rolling
- `:25.08` -- FSDK minor line
- `:25.08.13` -- FSDK point release (treated immutable)

Every image self-declares its base via `io.projectbluefin.fsdk.version` and
`io.projectbluefin.fsdk.ref` labels.

## Build locally

Requires `podman` and [`just`](https://github.com/casey/just). BuildStream runs
inside the FSDK `bst2` container -- nothing to install.

    just validate        # resolve the element graph
    just build           # build + load ghcr.io/projectbluefin/base:latest
    just verify          # assert distroless + certs + tzdata
    just tags            # show derived tags

## License

Apache-2.0.
