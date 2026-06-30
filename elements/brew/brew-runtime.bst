kind: compose
description: |
  Carve the brew dependency stack to a runtime rootfs. This is a developer
  environment, NOT a distroless image: the SLIM recipe does NOT apply here.
  We KEEP shells, locale, timezone data, sysconf, and devel headers (brew builds
  some formulas from source). Only genuinely useless-in-a-container content is
  dropped.

build-depends:
  - brew/brew-deps.bst

config:
  exclude:
    - debug      # debug symbols
    - doc        # man pages / docs
    - tests      # installed-tests
