---
name: verify-distroless
description: Run and understand the distroless + slim verification gates. Use when validating an image before merge, debugging a failed gate, or adding a new gate.
metadata:
  context7-sources:
    - /apache/buildstream
---

# Verify Distroless

`just verify` is the merge contract. It builds nothing — it inspects the loaded
`ghcr.io/projectbluefin/<name>:latest` image. All gates must pass.

## The gates

1. **No shell binary in rootfs.** Exports the container filesystem and greps for
   `(ba)?sh` in the path list. The bash binary lives in FSDK's `runtime` domain
   (NOT `shells`), so it is removed by explicit `rm` in the SLIM recipe, not by a
   compose exclude.
2. **CA certificates present** — `etc/(ssl|pki)/.*(ca-bundle|cert)` in the rootfs.
3. **tzdata present** — `usr/share/zoneinfo/UTC`. A kept crash-preventer.
4. **Slim bloat removed** — fails if `terminfo` or any
   `lib{asan,tsan,lsan,ubsan,hwasan,gfortran}.so` reappears. Regression guard for
   the SLIM recipe.

## Run it

```
just verify
```

Rootless podman works; the recipe auto-detects and only uses `sudo` if `podman
info` fails.

## Debugging a failure

Export the rootfs and inspect directly. Distroless images have no CMD or
ENTRYPOINT in their OCI config — `podman create` requires a placeholder command
to succeed (it does not validate whether the command exists in the image):

```
cid=$(podman create ghcr.io/projectbluefin/<name>:latest /nonexistent)
podman export "$cid" | tar -tf - | grep -E '<thing you expect/don.t expect>'
podman rm "$cid"
```

A functional smoke test (loader + libc) on a distroless image — run a real binary,
not a shell:

```
podman run --rm ghcr.io/projectbluefin/<name>:latest /usr/bin/env
```

## Adding a gate

When you cut something in the SLIM recipe that must stay gone, add a matching
`grep` assertion to gate `[4/N]` in the `verify` recipe so the build fails if it
creeps back. Renumber the gate labels.

When creating a new image or modifying an existing one, ALWAYS add a smoke test
that executes the primary binary directly (e.g. `podman run --rm ... /usr/bin/skopeo --version`).
Distroless images have no shell to drop into, and `ldd` inside BuildStream's sandbox
does not replicate the minimal container rootfs. A binary might link inside the sandbox
but fail to run in the final OCI image because a shared library was stripped by the
`compose` element. The only way to prove all dynamic dependencies made it into the image
is to execute the binary.
