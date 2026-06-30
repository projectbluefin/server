kind: stack
description: |
  Dependency set for the Homebrew nspawn machine image. NOT distroless: this is a
  full developer environment. Reuses base/base-stack.bst (glibc, coreutils, bash,
  CA certs, tzdata, os-release, ldconfig) and adds an init (systemd) plus the
  runtime tools Homebrew needs to operate (ruby, git, curl, a compiler toolchain,
  and the common unix utilities brew shell scripts shell out to).

depends:
  # Foundation (also used by the distroless base image).
  - base/base-stack.bst

  # Init so `machinectl start` works and the container can run long-lived.
  - freedesktop-sdk.bst:components/systemd.bst

  # Brew's own runtime requirements.
  - freedesktop-sdk.bst:components/ruby.bst            # brew is written in Ruby
  - freedesktop-sdk.bst:components/git.bst             # taps + self-update
  - freedesktop-sdk.bst:components/curl.bst            # bottle downloads
  - freedesktop-sdk.bst:components/gcc.bst             # source builds / compiler
  - freedesktop-sdk.bst:components/patchelf.bst        # bottle relocation on Linux

  # Common unix tooling brew and formulas shell out to at runtime.
  - freedesktop-sdk.bst:components/make.bst
  - freedesktop-sdk.bst:components/patch.bst
  - freedesktop-sdk.bst:components/diffutils.bst
  - freedesktop-sdk.bst:components/which.bst
  - freedesktop-sdk.bst:components/procps.bst
  - freedesktop-sdk.bst:components/tar.bst
  - freedesktop-sdk.bst:components/gzip.bst
  - freedesktop-sdk.bst:components/xz.bst
  - freedesktop-sdk.bst:components/zstd.bst
  - freedesktop-sdk.bst:components/sed.bst
  - freedesktop-sdk.bst:components/gawk.bst
  - freedesktop-sdk.bst:components/grep.bst
  - freedesktop-sdk.bst:components/findutils.bst
  - freedesktop-sdk.bst:components/file.bst
  - freedesktop-sdk.bst:components/util-linux.bst

  # User-management files/tools (useradd, /etc/login.defs, subuid support).
  - freedesktop-sdk.bst:components/shadow.bst
