kind: manual
description: |
  Declare this image's identity at /usr/share/ublue-os/image-info.json.

  The shared countme reporter from projectbluefin/common reads this file to know
  which image it is counting. Every other image in the family already writes one;
  this image is a DDI rather than an OCI image, so it has no image-info.json of
  its own and no bootc ref to fall back to.

  Only image-name is declared. A DDI is delivered by systemd-sysupdate and has no
  container tag or flavor, and the reporter omits fields it is not given rather
  than sending a placeholder.

build-depends:
  - base/base-stack.bst

variables:
  strip-binaries: ""

config:
  install-commands:
    - mkdir -p "%{install-root}%{datadir}/ublue-os"
    - |
      cat >"%{install-root}%{datadir}/ublue-os/image-info.json" <<'JSON'
      {
        "image-name": "server"
      }
      JSON
