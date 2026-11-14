kind: manual
description: |
  Bluefin Server os-release. IMAGE_ID/IMAGE_VERSION identify the image to
  systemd-sysupdate and systemd-sysext; extensions match on ID=bluefin-server.

(@):
- include/arch.yml
- include/image.yml

build-depends:
- base/base-stack.bst

variables:
  strip-binaries: ""

config:
  install-commands:
  - mkdir -p "%{install-root}/usr/lib"
  - |
    # GPT labels (bluefin_usr_verity_%A in files/os/repart.d) hold 36 characters.
    v='%{image-version}'
    [ "${#v}" -le 17 ] || { echo "ERROR: image-version ${v} is longer than 17 characters" >&2; exit 1; }
  - |
    cat <<EOF > "%{install-root}/usr/lib/os-release"
    NAME="Bluefin Server"
    ID=bluefin-server
    VERSION="%{image-version}"
    VERSION_ID=%{image-version}
    PRETTY_NAME="Bluefin Server %{image-version}"
    IMAGE_ID=bluefin-server
    IMAGE_VERSION=%{image-version}
    ARCHITECTURE=%{systemd-arch}
    ANSI_COLOR="0;38;5;33"
    HOME_URL="https://github.com/projectbluefin/server"
    BUG_REPORT_URL="https://github.com/projectbluefin/server/issues"
    EOF
  - |
    # PID 1 uses this file's mtime as its clock floor, not the SDK's 2011 epoch.
    v='%{installer-version}'
    month="${v#*.}"
    epoch="%{install-root}/usr/lib/clock-epoch"
    date -u -d "20${v%%.*}-${month%%.*}-01" +%s > "${epoch}"
    touch -d "@$(cat "${epoch}")" "${epoch}"
    chmod 0644 "${epoch}"
