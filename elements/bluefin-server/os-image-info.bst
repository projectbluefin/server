kind: manual
description: |
  Declare this image's identity at /usr/share/ublue-os/image-info.json.

  The shared countme reporter from projectbluefin/common reads this file to know
  which image it is counting. Every other image in the family already writes one;
  this image is a DDI rather than an OCI image, so it has no image-info.json of
  its own and no bootc ref to fall back to.

  image-name is the count. image-tag is the stream this image follows: it is
  updated by systemd-sysupdate from GitHub Releases `latest`, the only channel
  in files/os/sysupdate.d/*.transfer (Path=.../releases/latest/download/), so
  `latest` is the same kind of answer the OCI images give with stable or testing
  (projectbluefin/server#97). It is not the DDI version. A unit test keeps it
  equal to the transfers' channel. No image-flavor: a DDI has no flavors.

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
        "image-name": "server",
        "image-tag": "latest"
      }
      JSON
