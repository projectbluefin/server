kind: compose
description: Chisel the static stack to runtime-only, no glibc.

build-depends:
  - static/static-stack.bst

config:
  exclude:
    - debug
    - devel
    - doc
    - locale
    - static-blocklist
    - vm-only
    - tests
    - shells
