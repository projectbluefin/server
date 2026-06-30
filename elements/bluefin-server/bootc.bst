kind: manual
description: Build bootc from source using cargo and FSDK libraries.

build-depends:
  - freedesktop-sdk.bst:components/rust.bst
  - freedesktop-sdk.bst:components/pkg-config.bst
  - freedesktop-sdk.bst:components/git-minimal.bst

depends:
  - freedesktop-sdk.bst:components/ostree.bst
  - freedesktop-sdk.bst:components/glib.bst
  - freedesktop-sdk.bst:components/openssl.bst

sources:
  - kind: git_repo
    url: https://github.com/containers/bootc.git
    track: main
    ref: 525d56cd31be7144a507f451db5ad87ccb816640

config:
  build-commands:
    - cargo build --release --locked

  install-commands:
    - mkdir -p "%{install-root}/usr/bin"
    - cp target/release/bootc "%{install-root}/usr/bin/bootc"
