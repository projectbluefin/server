kind: manual
description: Build bootc from offline vendored sources.

build-depends:
  - freedesktop-sdk.bst:components/rust.bst
  - freedesktop-sdk.bst:components/pkg-config.bst
  - freedesktop-sdk.bst:components/git-minimal.bst
  - freedesktop-sdk.bst:components/make.bst
  - freedesktop-sdk.bst:components/tar.bst
  - freedesktop-sdk.bst:components/zstd.bst

depends:
  - freedesktop-sdk.bst:components/ostree.bst
  - freedesktop-sdk.bst:components/glib.bst
  - freedesktop-sdk.bst:components/openssl.bst

sources:
  - kind: remote
    url: https://github.com/bootc-dev/bootc/releases/download/v1.16.2/bootc-1.16.2-vendor.tar.zstd
    filename: bootc-vendor.tar.zstd
    ref: 53d759ca521144a675af67e68d23c3f5f18dca784e4e900052d0cfdc4467732b

variables:
  strip-binaries: ""

config:
  build-commands:
    - |
      tar --zstd -xf bootc-vendor.tar.zstd
      cargo build --release --frozen

  install-commands:
    - |
      mkdir -p "%{install-root}/usr/bin"
      cp target/release/bootc "%{install-root}/usr/bin/bootc"
