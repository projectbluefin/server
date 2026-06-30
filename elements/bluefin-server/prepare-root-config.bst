kind: manual
description: Create the required ostree/prepare-root.conf configuration file for bootc and ostree-prepare-root.

build-depends:
  - freedesktop-sdk.bst:components/make.bst

config:
  install-commands:
    - mkdir -p "%{install-root}/usr/lib/ostree"
    - |
      cat <<EOF > "%{install-root}/usr/lib/ostree/prepare-root.conf"
      [sysroot]
      readonly=false
      EOF
