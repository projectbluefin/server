kind: compose
description: Chisel the qemu-img stack to runtime-only.

build-depends:
  - qemu-img/qemu-img-stack.bst

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

