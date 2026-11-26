kind: import
description: |
  Secure Boot signing keys (PK, KEK, DB: certificate and private key each),
  staged at /boot-keys for the elements that sign boot components or Secure
  Boot variable updates only (efi-keys, os-sd-boot-signed, shim,
  bluefin-server-boot). Never add this element to a runtime stack: its
  artifact holds private keys. Generate local dogfood keys with
  `just gen-dev-keys`.

config:
  target: /boot-keys

sources:
- kind: local
  path: files/boot-keys/PK.crt
- kind: local
  path: files/boot-keys/PK.key
- kind: local
  path: files/boot-keys/KEK.crt
- kind: local
  path: files/boot-keys/KEK.key
- kind: local
  path: files/boot-keys/DB.crt
- kind: local
  path: files/boot-keys/DB.key
