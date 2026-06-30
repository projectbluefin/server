kind: compose
description: Chisel the skopeo stack to runtime-only, distroless.

build-depends:
  - skopeo/skopeo-stack.bst

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
