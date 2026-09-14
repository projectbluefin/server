kind: manual
description: |
  Weekly first-party countme reporting.

  The reporter is not defined here. It is taken from projectbluefin/common
  system_files/shared, the same unit and helper every other image ships, so this
  image counts through exactly the same bluefin-countme as the rest of the family.

  The preset from common enables the timer; this image applies systemd presets,
  so no enablement symlink is needed.

sources:
  - kind: git_repo
    url: github:projectbluefin/common.git
    track: main
    ref: v2026.08-108-gd46c4df9f9988002120cff4a66df8b163070fe6d

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
    - install -Dm755 system_files/shared/usr/libexec/bluefin-countme "%{install-root}%{prefix}/libexec/bluefin-countme"
    - install -Dm644 system_files/shared/usr/lib/systemd/system/bluefin-countme.service -t "%{install-root}%{prefix}/lib/systemd/system/"
    - install -Dm644 system_files/shared/usr/lib/systemd/system/bluefin-countme.timer -t "%{install-root}%{prefix}/lib/systemd/system/"
    - install -Dm644 system_files/shared/usr/lib/systemd/system-preset/03-bluefin-countme.preset -t "%{install-root}%{prefix}/lib/systemd/system-preset/"
