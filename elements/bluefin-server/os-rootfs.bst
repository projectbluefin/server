kind: compose
description: Compose the Bluefin Server target rootfs into a single stageable artifact.

build-depends:
  - bluefin-server/os-stack.bst
  - freedesktop-sdk.bst:components/dracut.bst

config:
  exclude:
    - debug
    - devel
    - doc
