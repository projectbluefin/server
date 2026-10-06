kind: manual
description: |
  First-party countme reporting.

  The reporter is not defined here. It is taken from projectbluefin/common main,
  system_files/shared, the same unit and helper every other image ships, so this
  image counts through exactly the same projectbluefin-countme as the rest of the
  family. It identifies the image from /usr/share/ublue-os/image-info.json
  (os-image-info.bst).

  The preset from common enables the timer; this image applies systemd presets,
  so no enablement symlink is needed. The service honours common's opt-outs:
  `systemctl mask --now projectbluefin-countme.timer`, or any of the opt-out
  files its unit lists (for example /etc/projectbluefin/countme/disabled).

  Common's reporter currently counts only bootc-booted Dakota and Utah images
  (its unit requires /run/ostree-booted and it reads the stream from
  `bootc status`), so on this DDI it does nothing and never touches the network
  until common extends its scope; re-tracking this element picks that up.

sources:
  - kind: git_repo
    url: github:projectbluefin/common.git
    track: main
    ref: v2026.08-272-ge4162845362d60593117480660f5470abc00af80

build-depends:
  - base/base-stack.bst

depends:
  # The reporter reads image metadata with jq and sends the ping with curl.
  - freedesktop-sdk.bst:components/curl.bst
  - freedesktop-sdk.bst:components/jq.bst
  - bluefin-server/os-image-info.bst

variables:
  strip-binaries: ""

config:
  install-commands:
    - install -Dm755 system_files/shared/usr/libexec/projectbluefin-countme "%{install-root}%{prefix}/libexec/projectbluefin-countme"
    - install -Dm644 system_files/shared/usr/lib/systemd/system/projectbluefin-countme.service -t "%{install-root}%{prefix}/lib/systemd/system/"
    - install -Dm644 system_files/shared/usr/lib/systemd/system/projectbluefin-countme.timer -t "%{install-root}%{prefix}/lib/systemd/system/"
    - install -Dm644 system_files/shared/usr/lib/systemd/system-preset/03-projectbluefin-countme.preset -t "%{install-root}%{prefix}/lib/systemd/system-preset/"
