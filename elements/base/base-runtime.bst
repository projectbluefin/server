kind: compose
description: Chisel the base stack down to runtime-only, distroless.

build-depends:
  - base/base-stack.bst

config:
  exclude:
    - debug
    - devel
    - doc
    - locale
    - static-blocklist
    - vm-only
    - tests
    # NOTE: 'shells' covers only /usr/share/fish and /usr/share/zsh data dirs.
    # It does NOT include the bash binary (/usr/bin/bash, /usr/bin/sh -> bash),
    # which lives in the 'runtime' split domain. The actual shell-binary removal
    # that achieves distroless happens via an explicit rm -f in elements/oci/base.bst.
    - shells
