kind: manual

description: |
  Install first-boot systemd credential provisioning contracts into the target OS.
  Supports sysusers credentials, systemd-network-generator network.* credentials,
  and the firstboot.* credentials (locale, keymap, timezone, hostname).

  Flatcar's /usr is built without systemd-firstboot, so the firstboot.*
  credentials are applied by /usr/libexec/bluefin-firstboot-credentials, a
  bash + coreutils helper that writes the same files systemd-firstboot would
  (/etc/locale.conf, /etc/vconsole.conf, /etc/localtime) and additionally
  /etc/hostname plus the live kernel hostname from firstboot.hostname, which
  systemd <= v259 (Flatcar's) does not read; systemd v260 added it as a
  static hostname honoured only when none is set, while this helper applies
  it unconditionally.

build-depends:
  - base/base-stack.bst

sources:
  - kind: local
    path: files/os/sysusers.d
    directory: sysusers-src
  - kind: local
    path: files/os/creds/systemd/system
    directory: systemd-src
  - kind: local
    path: files/os/libexec
    directory: libexec-src

# Disable binary stripping; this element only installs text files and the
# runtime-minimal sandbox does not include the stripper toolchain.
variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail

      install -Dm0644 sysusers-src/*.conf -t "%{install-root}/usr/lib/sysusers.d/"
      mkdir -p "%{install-root}/usr/lib/systemd/system"
      cp -a systemd-src/. "%{install-root}/usr/lib/systemd/system/"
      install -Dm0755 libexec-src/bluefin-firstboot-credentials \
        "%{install-root}/usr/libexec/bluefin-firstboot-credentials"
