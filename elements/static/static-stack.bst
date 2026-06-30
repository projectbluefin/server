kind: stack
description: |
  Minimal static runtime: CA certificates and timezone data only.
  No glibc, no libc at all. For statically compiled binaries (Go
  programs compiled with CGO_ENABLED=0). Mirrors gcr.io/distroless/static.

depends:
  - freedesktop-sdk.bst:components/ca-certificates.bst
  - freedesktop-sdk.bst:components/tzdata.bst
  - freedesktop-sdk.bst:components/os-release.bst
  - freedesktop-sdk.bst:integration/extra-fs.bst
