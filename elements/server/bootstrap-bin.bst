kind: manual
description: |
  Bluefin's stdlib-only native cluster lifecycle helper. Uses the cached FSDK
  Go toolchain; no upstream Console or Argo source is built here.

(@):
- include/arch.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/buildsystem-go.bst

variables:
  optimize-debug: "false"
  go_ldflags: "-compressdwarf=false -linkmode=internal"

environment:
  CGO_ENABLED: "0"
  GOOS: linux
  GOARCH: "%{go-arch}"
  GOAMD64: v1
  GOARM64: v8.0
  GOPATH: "%{build-root}/.go"
  GOCACHE: "%{build-root}/.cache/go-build"
  GOPROXY: "off"
  GOTOOLCHAIN: local

config:
  build-commands:
  - go build -trimpath -buildvcs=false -o bluefin-server-bootstrap .
  install-commands:
  - install -Dm755 bluefin-server-bootstrap "%{install-root}/usr/libexec/bluefin-server-bootstrap"
  - |
    %{install-extra}

sources:
- kind: local
  path: files/server/bootstrap
