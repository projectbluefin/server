---
name: nspawn-machine-image
description: Build a non-distroless systemd-nspawn machine image (a rootfs .tar.zst for machinectl import-tar) from FSDK. Use when adding a full dev-environment container (like brew) instead of an OCI distroless image.
metadata:
  context7-sources:
    - /apache/buildstream
---

# nspawn Machine Image (rootfs tarball)

Use when an image must be a **full Linux dev environment** booted by
`systemd-nspawn` / `machinectl`, not a distroless OCI image. Reference
implementation: the `brew` image (`elements/brew/*`, `elements/oci/brew-nspawn.bst`,
spec in `docs/brew-nspawn-container-spec.md`).

## When NOT to Use

- You want a normal container image → use the OCI pattern (`add-new-image.md`).
- The thing already ships an official upstream image → consume it.

## How it differs from the distroless images

| | Distroless OCI (`base`) | nspawn machine image (`brew`) |
|---|---|---|
| Output | OCI image via `build-oci` | `.tar.zst` rootfs via `tar` |
| Shell | removed | **kept** (`bash` required) |
| SLIM recipe | applied | **NOT applied** |
| Init | none | `systemd` + `/sbin/init` |
| Locale/devel | stripped | kept (formulas build from source) |
| Consumed by | `podman`/`docker` | `machinectl import-tar` |

## Element chain

1. `*-runtime.bst` (`stack`) — reuse `base/base-stack.bst`, add `components/systemd.bst`
   plus the runtime tools (ruby, git, curl, gcc, make, patch, diffutils, which,
   procps, tar/gzip/xz/zstd, sed/gawk/grep/findutils, file, util-linux, shadow).
   On Linux also add `components/patchelf.bst` (Homebrew bottle relocation).
2. `*-deps.bst` (`manual`) — stage the app tree directly from a `git_repo` source 
   (do NOT run network installers in the sandbox; "untar in place" the repo).
3. `oci/<name>.bst` (`script`) — assemble the tarball (below).

## The assembly script (the divergence)

Stage the runtime + prefix at `/layer`; put the assembly toolchain
(`base-stack` + `components/tar.bst` + `components/zstd.bst`) at the sandbox root.
Then finalise container bits and tar:

```sh
# zstd: 3-5x faster decompression than gzip; systemd-sysupdate handles .tar.zst.
tar --numeric-owner --xattrs --zstd -cf "%{install-root}/<name>-%{version}.tar.zst" -C /layer .
sha256sum --binary "<name>-%{version}.tar.zst" > SHA256SUMS   # for systemd-sysupdate
```

Get the artifact out with `bst artifact checkout <oci elem> --directory dist`.

## Hard-won gotchas

- **No `grep` in the assembly toolchain.** `base-stack`/`runtime-minimal` ship
  coreutils, not grep. Author `/etc/passwd` etc. with `printf`, not
  `grep || echo` append.
- **No heredocs for file content in YAML-indented shell.** `<<'EOF'` keeps the
  YAML block's leading spaces and corrupts `/etc/passwd`. Use `printf '...\n...'`.
- **Cannot `chown` to uid 1001 in the sandbox** — the bst user namespace returns
  `EINVAL`. Don't try. For nspawn with `PrivateUsers=no` + `Bind=/home/<user>`,
  the **host** establishes ownership via the bind mount; image-side ownership is
  irrelevant. Document this rather than fighting it.
- **usr-merge symlinks:** `/bin`, `/sbin`, `/lib` are symlinks to `usr/*`. So
  `/sbin/init` resolves to `usr/bin/init`, and a tarball has no literal
  `./bin/bash` entry — verify the real `./usr/bin/...` paths.
- **init:** create `/sbin/init -> /usr/lib/systemd/systemd` (resolves through the
  usr-merge symlink) so `machinectl start` boots.
- **machine-id:** ship an **empty** `/etc/machine-id` so systemd first-boot
  provisions a unique id per imported machine.
- **service users:** a minimal `/etc/passwd` (root + app user) is enough;
  `systemd-sysusers` regenerates `systemd-*` users at first boot (keep the
  `sysusers.d` content — i.e. do not exclude `vm-only`).
- **zstd needs the `zstd` binary in the toolchain.** `tar --zstd` shells out to
  `zstd`; add `components/zstd.bst` to the assembly element's `build-depends`,
  not just to the runtime. `.tar.zst` decompresses 3-5x faster than gzip and
  systemd-sysupdate (`url-tar` / `Type=url-tar`) handles it natively.

## Verification

`just verify-brew` exports the tarball and asserts the real `usr/bin/*` paths,
the init symlink, locale.conf, machine-id, and the app user at uid 1001. Booting
(`machinectl import-tar` + `machinectl start`) requires a systemd host and is not
done in CI here — note it as an integration step.
