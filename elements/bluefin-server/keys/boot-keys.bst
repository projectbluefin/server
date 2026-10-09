kind: import
description: |
  Secure Boot and module signing private material, staged at /boot-keys for
  the signing elements only (kernel-modules, efi-keys, os-sd-boot-signed,
  shim, openzfs-signed, nvidia-open-*-signed, bluefin-server-boot,
  bluefin-server-image).
  Never add this element to a runtime stack: its artifact holds private keys.
  Generate local dogfood keys with `just gen-dev-keys`.

config:
  target: /boot-keys

sources:
- kind: local
  path: files/boot-keys
