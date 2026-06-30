---
name: slim-an-image
description: The SLIM recipe — what to strip from an FSDK-carved image, the size levers, and their risk tiers. Use when shrinking an image or extending the shared slim block.
metadata:
  context7-sources:
    - /apache/buildstream
---

# Slim an Image

Use when an image is too large, or when extending the shared SLIM recipe.

## Why a manual recipe

FSDK split-rule domains only cover:
`devel, debug, doc, sysconf, tests, shells, static-blocklist, license, locale,
vm-only, zoneinfo`. The largest **runtime-domain** bloat has *no domain* to exclude
it, so it must be removed explicitly with `rm` — the same pattern used for bash.
The shared block lives in `elements/oci/base.bst` under "SLIM RECIPE".

## Applies to every image — not just glibc images

Even a "static" image (no glibc by design, e.g. one that only adds tzdata + CA
certs) **must run the full SLIM recipe**. Reason: `tzdata.bst` has a runtime dep on
`runtime-minimal`, which carries glibc, gcc runtimes (libasan, libtsan, libgfortran),
and terminfo into any compose that includes it. Skipping the SLIM recipe on a
"minimal" image will fail gate `[4/4]` of `just verify`.

Rule: copy the full SLIM block from `oci/base.bst` into every new OCI script.

```
rm -rf _sizecheck
just bst artifact checkout <name>/<name>-runtime.bst --directory _sizecheck
du -sh _sizecheck && du -ah _sizecheck/usr | sort -rh | head -20
rm -rf _sizecheck
```

`_sizecheck` must be a project-relative path — the bst container only sees `/src`
(the repo). An absolute `/tmp/...` path is written inside the container and lost.

## Risk tiers

**Zero risk — always cut:**
- `usr/share/terminfo` (~12 MB) — terminal capability DB, useless in containers.
- gcc sanitizer runtimes `lib{asan,tsan,lsan,ubsan,hwasan}.so*` (~5 MB) — debug only.
- `libgfortran.so*` (~3.6 MB) — FORTRAN runtime pulled by gcc-libs.
- glibc `locale-archive`, `usr/share/i18n/charmaps` (~3 MB).
- leaked build tools: `localedef`, `sln`, `iconvconfig`, `ldconfig`, `pcre2test`.
- extra pcre2 widths `libpcre2-16/32`, `libpcre2-posix` (keep the 8-bit lib).

**Medium risk — trim, don't gut:**
- `gconv/` charset modules (~8 MB). Keep `gconv-modules*`, `UTF*`, `UNICODE*`,
  `ISO8859-1`, `ISO8859-15`, `CP1252`, `ANSI_X3.110`. Dropping a charset makes
  `iconv`/`.decode()` raise `LookupError` for that encoding (UTF-8 is built into
  glibc and always works).

**Do NOT cut (crash-preventers, cheap):**
- `tzdata` (`usr/share/zoneinfo`, ~2.6 MB) — python `zoneinfo` raises
  `ZoneInfoNotFoundError` without it. This is our differentiator vs suites that
  make you `pip install tzdata`.
- CA certificates + `usr/share/pki` trust source.
- `libstdc++`, `libgcc_s`, `libgomp` — C++ / OpenMP runtimes apps link.

## Sandbox constraint

The oci-builder sandbox has **no `find`**. Use shell globs + `case`:

```sh
for g in "$L"/usr/lib/*/gconv; do
  [ -d "$g" ] || continue
  for f in "$g"/*; do
    case "${f##*/}" in
      gconv-modules*|UTF*|UNICODE*|ISO8859-1.so|ISO8859-15.so|CP1252.so|ANSI_X3.110.so) : ;;
      *) rm -f "$f" ;;
    esac
  done
done
```

## Lock it in

Add a regression assertion to `just verify` (gate `[4/4]`) for anything you cut
that must stay gone, so it fails the build if it creeps back.

## Reference result

`base`: ~73 MB rootfs → **~40 MB image** after slim, all `just verify` gates green.
