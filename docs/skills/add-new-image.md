---
name: add-new-image
description: Scaffold a new distroless image (python, node, ruby, etc.) carved from FSDK components. Use when adding a new language runtime or tool image to fsdk-containers.
metadata:
  context7-sources:
    - /apache/buildstream
---

# Add a New Distroless Image

Use when adding a new runtime/tool image (e.g. `python`, `node`) carved from FSDK.

## When NOT to Use

- The tool already ships an official, maintained CNCF/upstream distroless image
  (e.g. `kubectl`). Consume that upstream image instead — do not rebuild it here.
- You only need to shrink an existing image → `slim-an-image.md`.

## Prereqs

Check the component exists in FSDK first:

```
just bst show freedesktop-sdk.bst:components/python3.bst
```

If FSDK has no component for it, it is a "CNCF tool" case (static Go binary etc.),
which is a different, heavier workflow — discuss before starting.

## The three-element pattern

Mirror `elements/base/` + `elements/oci/base.bst`:

1. **`elements/<name>/<name>-stack.bst`** (`kind: stack`) — list the FSDK deps:
   the runtime component plus `base/base-stack.bst` essentials (glibc, ca-certs,
   tzdata). Depend on the existing base stack so you inherit the shared runtime.

2. **`elements/<name>/<name>-runtime.bst`** (`kind: compose`) — chisel: copy the
   `exclude:` domain list from `base/base-runtime.bst`
   (debug/devel/doc/locale/static-blocklist/vm-only/tests/shells).

3. **`elements/oci/<name>.bst`** (`kind: script`) — stage the runtime at `/layer`,
   run the **shared SLIM block** (copy from `oci/base.bst`), then any
   **per-runtime prune**, then `build-oci`. Set the image title/labels and the
   `index-annotations` ref.name to `ghcr.io/projectbluefin/<name>:latest`.

### Per-runtime prune (the big win)

The shared slim block handles glibc/terminfo/etc. Each runtime ships its own bloat.
For **python** (FSDK stdlib is ~51 MB), additionally `rm -rf` from
`/layer/usr/lib/python3.*/`:

- `test/` and `*/test/`, `*/tests/` — stdlib test suites
- `ensurepip/`, `idlelib/`, `tkinter/`, `turtledemo/`, `turtle.py` — GUI / installer
- `lib2to3/`, `pydoc_data/`, `__phello__/`
- `config-*/`, `*.a` — static lib + build config
- Keep one of source vs `__pycache__`, not both, if you want to go further.

Document the prune list and *why each entry is safe* in this skill when you add it.

## Wire it up

- Add a `build-<name>` target or parameterize the Justfile (`image_name`).
- Add the image row to `README.md`.
- `just validate && just build && just verify`.

## Gotchas

- The oci-builder sandbox is minimal: **`find` is not available** — use shell globs
  and `case` (see `oci/base.bst`).
- Paths are arch-specific (`x86_64-linux-gnu` vs `aarch64-linux-gnu`). Use
  `/layer/usr/lib/*/...` globs so both arches work.
- **BST arch conditionals use `arch`, not `target_arch`.** The project option in
  `project.conf` is named `arch`. A conditional written as `target_arch == 'aarch64'`
  will fail with "variable 'target_arch' is undefined". The correct form is:
  ```yaml
  (?):
  - arch == 'aarch64':
      ...
  ```
- **`tzdata` pulls in `runtime-minimal` transitively.** `tzdata.bst` has a runtime
  dep on `runtime-minimal`, which includes glibc, gcc runtimes (libasan, libgfortran),
  and terminfo. Even a "static" image (no glibc by design) that includes tzdata will
  inherit all of this. Apply the **full SLIM recipe** (shell + sanitizer + terminfo
  removal) to every image without exception — see `slim-an-image.md`.
