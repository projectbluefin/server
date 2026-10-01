kind: manual
description: |
  Import the approved Flatcar Kubernetes raw system extension byte-for-byte.
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
  url: flatcar_extensions:kubernetes/kubernetes-v%{server-kubernetes-version}-%{systemd-arch}.raw
  ref: "%{server-kubernetes-sha256}"
  filename: kubernetes.raw

config:
  install-commands:
  - install -D -m 0444 kubernetes.raw "%{install-root}/server-kubernetes_%{image-version}.raw"
