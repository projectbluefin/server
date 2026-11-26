kind: manual
description: |
  Home Server engine selection and rootless owner preparation. The helpers
  select the optional Podman/Docker sysexts before they are fetched and
  prepare the first regular user for them afterwards. The unit is disabled by
  preset; the Home Server template enables it.

build-depends:
- base/base-stack.bst

sources:
- kind: local
  path: files/runtimes
  directory: runtime-src

variables:
  strip-binaries: ""

config:
  install-commands:
  - |
    set -eu
    lib="%{install-root}%{indep-libdir}"
    install -D -m0755 runtime-src/bluefin-oci-owner-prepare runtime-src/bluefin-oci-features -t "%{install-root}%{libexecdir}"
    install -D -m0644 runtime-src/bluefin-oci-owner-prepare.service "$lib/systemd/system/bluefin-oci-owner-prepare.service"
    install -D -m0644 runtime-src/bluefin-oci-features.service "$lib/systemd/system/bluefin-oci-features.service"
    install -D -m0644 runtime-src/80-bluefin-oci.preset "$lib/systemd/system-preset/80-bluefin-oci.preset"
