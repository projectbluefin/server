kind: compose
description: |
  Chisel the lab-runner stack to runtime-only. Shell binaries are
  intentionally kept — this is a CI utility container, not distroless.

build-depends:
  - lab-runner/lab-runner-stack.bst

config:
  exclude:
    - debug
    - devel
    - doc
    - locale
    - static-blocklist
    - vm-only
    - tests
