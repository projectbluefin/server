kind: import
description: |
  OpenPGP keyring that systemd-importd (diskless rd.systemd.pull) and
  systemd-sysupdate verify SHA256SUMS.gpg against, installed as
  /usr/lib/systemd/import-pubring.pgp, replacing the vendor keyring FSDK
  ships. Updates replace the trust root with /usr; /etc is an operator override.

  It comes from files/boot-keys/import-pubring.pgp, the public half of the
  key that signs this build's SHA256SUMS (bluefin-server-image.bst): a dev
  key from `just gen-dev-keys`, or on release builds the key in
  files/os/sysupdate-keys/import-pubring.gpg (CI copies it in).

# Stage systemd first so this keyring replaces its vendor keyring in both
# the OS and initrd, independent of the order of their stack dependencies.
runtime-depends:
  - freedesktop-sdk.bst:components/systemd.bst

public:
  bst:
    overlap-whitelist:
      - /usr/lib/systemd/import-pubring.pgp

sources:
  - kind: local
    path: files/boot-keys/import-pubring.pgp

config:
  target: /usr/lib/systemd
