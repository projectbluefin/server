kind: manual
description: |
  Import upstream Tailscale release binaries and units for the build architecture.

(@):
- include/arch.yml
- include/tailscale.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/sed.bst

variables:
  strip-binaries: ""

sources:
- kind: tar
  url: tailscale_pkgs:tailscale_%{tailscale-version}_amd64.tgz
  ref: "%{tailscale-x86-64-sha256}"
  base-dir: "tailscale_%{tailscale-version}_amd64"
  directory: dist

(?):
- arch == "aarch64":
    sources:
    - kind: tar
      url: tailscale_pkgs:tailscale_%{tailscale-version}_arm64.tgz
      ref: "%{tailscale-arm64-sha256}"
      base-dir: "tailscale_%{tailscale-version}_arm64"
      directory: dist

config:
  install-commands:
  - |
    set -euo pipefail
    bindir="%{install-root}%{bindir}"
    unitdir="%{install-root}%{indep-libdir}/systemd/system"
    defaultdir="%{install-root}%{datadir}/bluefin/tailscale"

    mkdir -p "${bindir}" "${unitdir}" "${defaultdir}"
    install -m 0755 dist/tailscaled "${bindir}/tailscaled"
    install -m 0755 dist/tailscale "${bindir}/tailscale"

    install -m 0644 dist/systemd/tailscaled.service "${unitdir}/tailscaled.service"
    install -m 0644 dist/systemd/tailscale-wait-online.service "${unitdir}/tailscale-wait-online.service"
    install -m 0644 dist/systemd/tailscale-online.target "${unitdir}/tailscale-online.target"
    install -m 0644 dist/systemd/tailscaled.defaults "${defaultdir}/tailscaled.defaults"

    # Bluefin /usr is merged; binaries live in /usr/bin. Adjust unit Exec paths.
    sed -i 's|/usr/sbin/tailscaled|/usr/bin/tailscaled|g' "${unitdir}/tailscaled.service"
    # Later EnvironmentFile= lines override earlier ones, so the image's
    # defaults must come first for /etc/default/tailscaled to win.
    sed -i 's|EnvironmentFile=/etc/default/tailscaled|EnvironmentFile=-/usr/share/bluefin/tailscale/tailscaled.defaults\nEnvironmentFile=-/etc/default/tailscaled|' "${unitdir}/tailscaled.service"
