kind: stack
description: |
  Skopeo runtime: base (glibc + CA + tzdata) plus skopeo and its
  container library dependencies (containers-common, gpgme, libassuan).

depends:
  - base/base-stack.bst
  - freedesktop-sdk.bst:components/skopeo.bst
  - freedesktop-sdk.bst:components/containers-common.bst
  - freedesktop-sdk.bst:components/gpgme.bst
  - freedesktop-sdk.bst:components/libassuan.bst
  - freedesktop-sdk.bst:components/sqlite.bst
  - freedesktop-sdk.bst:components/libgpg-error.bst
  - freedesktop-sdk.bst:components/glib.bst
  - freedesktop-sdk.bst:components/pkg-config.bst
