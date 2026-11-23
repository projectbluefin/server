kind: manual
description: |
  First-party countme reporting for Bluefin Server.

  Bluefin Server is a standalone DDI and does not consume projectbluefin/common.
  The reporter lives in this repository and identifies the image from
  /usr/share/ublue-os/image-info.json (os-image-info.bst): image-name `server`,
  no flavor, stream `latest` from image-tag. Its service, timer, and preset are
  base-OS units and presets that ship from files/os/systemd (os-k0s-first-boot.bst
  and os-sshd-preset.bst); this element installs only the reporter helper and
  its curl/jq runtime.

  Opt out: `systemctl mask --now projectbluefin-countme.timer`, or create
  /etc/projectbluefin/countme/disabled.

build-depends:
  - base/base-stack.bst

depends:
  # The reporter reads image metadata with jq and sends the ping with curl.
  - freedesktop-sdk.bst:components/curl.bst
  - freedesktop-sdk.bst:components/jq.bst
  - bluefin-server/os-image-info.bst

sources:
  - kind: local
    path: files/os/libexec
    directory: libexec-src

variables:
  strip-binaries: ""

config:
  install-commands:
    - |
      set -euo pipefail
      install -Dm0755 libexec-src/projectbluefin-countme \
        "%{install-root}/usr/libexec/projectbluefin-countme"
