kind: manual
description: |
  Render tracked vendored stock resources, immutable public bare-Git baseline,
  canonical stock-image lock and SPDX provenance using cached FSDK Git/Python.
  No generated host imports, upstream source builds or compatibility proof flags.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/_private/git-minimal.bst
- freedesktop-sdk.bst:components/python3.bst

variables:
  strip-binaries: ""

sources:
- kind: local
  path: files/server/manifests
  directory: stock

config:
  build-commands:
  - python3 stock/produce-baseline.py --source stock --output %{build-root}/platform-output
  install-commands:
  - mkdir -p %{install-root}
  - cp -a %{build-root}/platform-output/. %{install-root}/
