kind: manual
description: Create custom Flatcar-compatible os-release metadata to support Flatcar system extensions (sysext).

# %{flatcar-board} — derived from the `arch` option, never hardcoded here.
(@): include/arch.yml

build-depends:
  # Base runtime providing /bin/sh and coreutils (cat, ln, mkdir, sed) in the sandbox.
  - base/base-stack.bst

# Disable binary stripping; this element only creates text files and the
# runtime-minimal sandbox does not include the stripper toolchain.
variables:
  strip-binaries: ""

config:
  install-commands:
    - mkdir -p "%{install-root}/usr/lib"
    - |
      # %{release-version} is declared in project.conf and enforced against
      # the junction ref by check-release-version.py — no re-parsing needed.
      FLATCAR_VERSION="4593.2.3"

      cat <<EOF > "%{install-root}/usr/lib/os-release"
      NAME="Bluefin Server"
      ID=flatcar
      ID_LIKE=fedora
      VERSION="${FLATCAR_VERSION}-fsdk"
      VERSION_ID=${FLATCAR_VERSION}
      PRETTY_NAME="Bluefin Server %{release-version}"
      ANSI_COLOR="0;38;5;208"
      HOME_URL="https://github.com/projectbluefin/server"
      BUG_REPORT_URL="https://github.com/projectbluefin/server/issues"
      FLATCAR_BOARD="%{flatcar-board}"
      CPE_NAME="cpe:/o:flatcar-linux:flatcar_linux:${FLATCAR_VERSION}"
      IMAGE_VERSION=%{release-version}
      EOF
    - |
      mkdir -p "%{install-root}/etc"
      ln -s ../usr/lib/os-release "%{install-root}/etc/os-release"
