kind: manual
description: |
  Import the approved Flatcar containerd raw system extension byte-for-byte.
  This opaque payload is not unpacked or staged into the base OS /usr.
  The single output is addressed by Bluefin's image version for signed delivery;
  upstream runtime selection is pinned independently in include/server.yml.

(@):
- include/arch.yml
- include/image.yml
- include/server.yml

build-depends:
- base/base-stack.bst

variables:
  strip-binaries: ""

sources:
- kind: remote
  url: flatcar_extensions:containerd/containerd-%{server-containerd-version}-%{systemd-arch}.raw
  ref: "%{server-containerd-sha256}"
  filename: containerd.raw

config:
  install-commands:
  - install -D -m 0444 containerd.raw "%{install-root}/server-containerd_%{image-version}.raw"
