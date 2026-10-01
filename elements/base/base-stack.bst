kind: stack
description: |
  Build sandbox for this project's manual and script elements: glibc,
  runtime-gnu (/bin/sh and coreutils, which the ldconfig and
  ca-certificates integration commands also need in FSDK 26.08), CA
  certificates and timezone data. Nothing ships it; the OS payload is
  bluefin-server/os-base.bst.

depends:
  - freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst
