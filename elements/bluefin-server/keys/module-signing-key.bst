kind: import
description: |
  Kernel module signing key and its certificate, staged at /boot-keys for the
  elements that sign modules only (kernel-modules, openzfs-signed,
  nvidia-open-*-signed). Never add this element to a runtime stack: its
  artifact holds a private key.

  One element per kind of key, so an element's cache key moves only with the
  key it uses. Non-release builds all use the committed INSECURE dev module
  pair (files/dev-keys/), so this element, and the signed modules built from
  it, stay cached from one build to the next, while the Secure Boot and image
  signing keys are new every run. Generate local dogfood keys with
  `just gen-dev-keys`.

config:
  target: /boot-keys

sources:
- kind: local
  path: files/boot-keys/linux-module-cert.key
- kind: local
  path: files/boot-keys/modules/linux-module-cert.crt
  directory: modules
