kind: manual
description: Create custom Flatcar-compatible os-release metadata to support Flatcar system extensions (sysext).

build-depends:
  # Needed so the manual-element sandbox provides /bin/sh and coreutils (cat, ln, mkdir, sed).
  - freedesktop-sdk.bst:public-stacks/runtime-minimal.bst

# Disable binary stripping; this element only creates text files and the
# runtime-minimal sandbox does not include the stripper toolchain.
variables:
  strip-binaries: ""

sources:
  # The FSDK point release is the source of truth for the OS image version.
  - kind: local
    path: elements/freedesktop-sdk.bst

config:
  install-commands:
    - mkdir -p "%{install-root}/usr/lib"
    - |
      # Extract the FSDK point release (e.g. 25.08.13) from the pinned junction ref.
      FSDK_VERSION=""
      while read -r line; do
        if [[ "${line}" =~ ref:[[:space:]]+freedesktop-sdk-([0-9]+\.[0-9]+\.[0-9]+)- ]]; then
          FSDK_VERSION="${BASH_REMATCH[1]}"
          break
        fi
      done < freedesktop-sdk.bst
      if [ -z "${FSDK_VERSION}" ]; then
        echo "ERROR: Could not determine FSDK version from freedesktop-sdk.bst" >&2
        exit 1
      fi

      # Flatcar-compatible version used by systemd-sysext / Flatcar Bakery matching.
      FLATCAR_VERSION="4593.2.3"

      cat <<EOF > "%{install-root}/usr/lib/os-release"
      NAME="Bluefin Server"
      ID=flatcar
      ID_LIKE=fedora
      VERSION="${FLATCAR_VERSION}-fsdk"
      VERSION_ID=${FLATCAR_VERSION}
      PRETTY_NAME="Bluefin Server ${FSDK_VERSION}"
      ANSI_COLOR="0;38;5;208"
      HOME_URL="https://github.com/projectbluefin/server"
      BUG_REPORT_URL="https://github.com/projectbluefin/server/issues"
      FLATCAR_BOARD="amd64-usr"
      CPE_NAME="cpe:/o:flatcar-linux:flatcar_linux:${FLATCAR_VERSION}"
      IMAGE_VERSION=${FSDK_VERSION}
      EOF
    - |
      mkdir -p "%{install-root}/etc"
      ln -s ../usr/lib/os-release "%{install-root}/etc/os-release"
