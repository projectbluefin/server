kind: manual
description: |
  Install the root credential persistence helper and enable its units.

  /etc/shadow lives inside the OS DDI, which systemd-sysupdate replaces in both
  root slots on every update. A root password rotated on the running host would
  otherwise roll back to the credential baked into the image as soon as the
  other slot boots, so this image keeps the authoritative root entry in the
  persistent /var partition and reconciles /etc/shadow with it on every boot.

  The units themselves are staged by bluefin-server/os-k0s-first-boot.bst, which
  installs files/os/systemd/system into /usr/lib/systemd/system. Enablement is an
  explicit multi-user.target.wants symlink created here: systemd presets are not
  applied in this image, so a preset would not enable anything.

  bluefin-root-cred-persist.service is intentionally left unenabled — it is the
  triggered half of bluefin-root-cred-persist.path, and starting it at boot
  could persist the image's baked-in credential over the operator's.

build-depends:
  - base/base-stack.bst

sources:
  - kind: local
    path: files/os/libexec
    directory: libexec-src

# Disable binary stripping; this element only installs a shell script and the
# runtime-minimal sandbox does not include the stripper toolchain.
variables:
  strip-binaries: ""

config:
  install-commands:
    - install -Dm755 libexec-src/bluefin-root-cred-sync
      "%{install-root}%{prefix}/libexec/bluefin-root-cred-sync"
    - |
      set -euo pipefail
      wants="%{install-root}%{prefix}/lib/systemd/system/multi-user.target.wants"
      install -d -m 0755 "${wants}"
      ln -sf ../bluefin-root-cred.service "${wants}/bluefin-root-cred.service"
      ln -sf ../bluefin-root-cred-persist.path "${wants}/bluefin-root-cred-persist.path"