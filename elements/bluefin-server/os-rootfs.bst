kind: compose
description: Compose the Bluefin Server target rootfs into a single stageable artifact.

build-depends:
  # The compose plugin executes through a shell; keep it build-only.
  - freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
  - bluefin-server/os-stack.bst

config:
  exclude:
    - debug
    - devel
    - doc
