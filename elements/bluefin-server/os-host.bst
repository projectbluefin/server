kind: manual
description: |
  bluefin-host: the base OS's non-interactive runtime helpers in one static Go
  binary (files/homelab/cluster/cmd/bluefin-host, the bluefin-cluster module;
  standard library only, no cgo). Each helper keeps its old path as a symlink,
  /usr/libexec/bluefin-<name> -> ../bin/bluefin-host, and dispatches on that
  name, so unit files, documentation and bluefin-cluster's
  /usr/libexec/bluefin-hostname keep working:
  - update path: bluefin-update-status, bluefin-update-status-migrate,
    bluefin-update-pending, bluefin-reboot-lock (FleetLock client),
    bluefin-boot-deadline, bluefin-diskless-update-check,
    bluefin-sysext-fetch, bluefin-boot-origin;
  - first boot: bluefin-hostname, bluefin-firstboot-credentials,
    bluefin-repair-etc-modes, bluefin-migrate-etc-vendor;
  - bluefin-sysext-modules, which module sysexts' load units run.
  Unit drop-ins call `bluefin-host kube-interlock`, `kured-flag`,
  `mask-uki-transfer` and `boot-is-good` directly.

  Runtime tools it runs (os-base.bst): systemctl, journalctl, bootctl,
  systemd-analyze, systemd-id128, systemd-sysupdate, systemd-sysext,
  systemd-bless-boot, agetty, gpgv, depmod, modprobe. HTTP (FleetLock, the
  diskless boot server) is Go's net/http.

  `go vet` and the helpers' tests run in-element.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/go.bst

sources:
- kind: local
  path: files/homelab/cluster

environment:
  GOROOT: "%{libdir}/go"
  GOTOOLCHAIN: local
  GOPROXY: "off"
  GOFLAGS: -mod=vendor -trimpath -buildvcs=false
  CGO_ENABLED: "0"

variables:
  # -s -w below already drops the symbol tables.
  strip-binaries: ""

config:
  build-commands:
  - |
    set -eu
    export GOPATH="${PWD}/.gopath" GOCACHE="${PWD}/.gocache"
    go vet ./cmd/bluefin-host/... ./internal/host/...
    go test ./cmd/bluefin-host/... ./internal/host/...
    go build -ldflags "-s -w" -o bluefin-host ./cmd/bluefin-host

  install-commands:
  - |
    set -eu
    install -D -m 0755 bluefin-host "%{install-root}/usr/bin/bluefin-host"
    mkdir -p "%{install-root}/usr/libexec"
    for helper in boot-deadline boot-origin diskless-update-check \
        firstboot-credentials hostname migrate-etc-vendor reboot-lock \
        repair-etc-modes sysext-fetch sysext-modules update-pending \
        update-status update-status-migrate; do
      ln -s ../bin/bluefin-host "%{install-root}/usr/libexec/bluefin-${helper}"
    done
