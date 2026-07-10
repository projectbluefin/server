kind: manual
description: Create custom Flatcar-compatible os-release metadata to support Flatcar system extensions (sysext).

build-depends:
  # Needed so the manual-element sandbox provides /bin/sh and coreutils (cat, ln, mkdir).
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

# Disable binary stripping; this element only creates text files and the
# runtime-minimal sandbox does not include the stripper toolchain.
variables:
  strip-binaries: ""

config:
  install-commands:
    - mkdir -p "%{install-root}/usr/lib"
    - |
      cat <<EOF > "%{install-root}/usr/lib/os-release"
      NAME="Flatcar Clone (FSDK)"
      ID=flatcar
      ID_LIKE=fedora
      VERSION="4593.2.3-fsdk"
      VERSION_ID=4593.2.3
      PRETTY_NAME="Flatcar Clone (FSDK) 4593.2.3-fsdk"
      ANSI_COLOR="0;38;5;208"
      HOME_URL="https://github.com/projectbluefin/testing-lab"
      BUG_REPORT_URL="https://github.com/projectbluefin/testing-lab/issues"
      FLATCAR_BOARD="amd64-usr"
      CPE_NAME="cpe:/o:flatcar-linux:flatcar_linux:4593.2.3"
      EOF
    - |
      mkdir -p "%{install-root}/etc"
      ln -s ../usr/lib/os-release "%{install-root}/etc/os-release"
