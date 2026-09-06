kind: stack
description: |
  Minimal distroless runtime: glibc + gcc-libs + base files, plus
  CA certificates and timezone data. No package manager. In FSDK 26.08,
  runtime-gnu provides /bin/sh for ldconfig and ca-certificates
  integration scripts; bash is removed by an explicit rm -f step in
  elements/oci/base.bst, not by a compose domain.

depends:
  - freedesktop-sdk.bst:public-stacks/runtime-gnu.bst
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:components/os-release.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
  - freedesktop-sdk.bst:integration/ldconfig.bst
