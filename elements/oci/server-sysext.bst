kind: manual
description: |
  Opt-in Bluefin Server lifecycle, runtime configuration and immutable
  upstream-image platform baseline. Flatcar raws remain unchanged payloads;
  application images are pulled from their pinned upstream registries.

(@):
- include/arch.yml
- include/image.yml
- include/server.yml
- include/sysext.yml

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:components/erofs-utils.bst
- freedesktop-sdk.bst:components/zstd.bst
- freedesktop-sdk.bst:components/jq.bst
- freedesktop-sdk.bst:components/sed.bst
- filename: server/bootstrap-bin.bst
  config:
    location: /bootstrap-bin
- filename: server/platform-payload.bst
  config:
    location: /platform

sources:
- kind: local
  path: files/server/bootstrap
  directory: bootstrap-src
- kind: local
  path: files/server/runtime
  directory: runtime-src
- kind: local
  path: files/server/sysext
  directory: sysext-src

variables:
  strip-binaries: ""
  sysext-name: "server"
  sysext-image: "server_%{image-version}"
  sysext-release: "server"
  sysext-version: "%{image-version}"
  sysext-architecture: "%{systemd-arch}"
  server-health-image: "docker.io/library/busybox:1.37.0@sha256:bdf57e528e45e4433820e045b29b4597825a1c9e38353532d90a01445013f82e"

config:
  install-commands:
  - |
    set -eu
    test -s /platform/platform-lock.json
    jq -e '.schema == 1
       and (.images.console.ref | test("@sha256:[a-f0-9]{64}$"))
       and (.images.argoexec.ref | test("@sha256:[a-f0-9]{64}$"))' \
      /platform/platform-lock.json >/dev/null
    baseline="$(cat /platform/baseline-commit)"
    test "$(jq -r .baseline_commit /platform/platform-lock.json)" = "${baseline}"
    root=sysext/usr
    unitdir="${root}/lib/systemd/system"
    mkdir -p "${unitdir}"
    install -Dm0755 /bootstrap-bin/usr/libexec/bluefin-server-bootstrap "${root}/libexec/bluefin-server-bootstrap"
    install -m0644 bootstrap-src/*.service "${unitdir}/"
    mkdir -p "${root}/share/bluefin-server"
    cp -a /platform/manifests /platform/baseline.git "${root}/share/bluefin-server/"
    install -Dm0644 /platform/baseline-commit "${root}/share/bluefin-server/baseline-commit"
    install -Dm0644 /platform/platform-lock.json "${root}/share/bluefin-server/platform-lock.json"
    install -Dm0644 /platform/baseline-integrity.json "${root}/share/bluefin-server/baseline-integrity.json"
    mkdir -p "${root}/lib/tmpfiles.d" "${root}/lib/modules-load.d" \
      "${root}/lib/sysctl.d" "${root}/lib/systemd/system-preset"
    install -Dm0644 runtime-src/containerd.service.d/20-bluefin-server.conf \
      "${unitdir}/containerd.service.d/20-bluefin-server.conf"
    install -Dm0644 runtime-src/kubelet.service.d/20-bluefin-server.conf \
      "${unitdir}/kubelet.service.d/20-bluefin-server.conf"
    install -Dm0644 runtime-src/80-bluefin-server-runtime.preset \
      "${root}/lib/systemd/system-preset/80-bluefin-server-runtime.preset"
    install -Dm0644 runtime-src/modules-load-bluefin-server-runtime.conf \
      "${root}/lib/modules-load.d/bluefin-server-runtime.conf"
    install -Dm0644 runtime-src/sysctl-90-bluefin-server-runtime.conf \
      "${root}/lib/sysctl.d/90-bluefin-server-runtime.conf"
    install -Dm0644 runtime-src/tmpfiles-bluefin-server-runtime.conf \
      "${root}/lib/tmpfiles.d/bluefin-server-runtime.conf"
    install -Dm0644 runtime-src/crictl.yaml "${root}/share/bluefin-server/runtime/crictl.yaml"
    mkdir -p "${root}/share/bluefin-server/runtime/containerd"
    sed 's|@SERVER_PAUSE_IMAGE@|%{server-pause-image}|g' runtime-src/containerd/config.toml.in \
      > "${root}/share/bluefin-server/runtime/containerd/config.toml"
    jq -n --arg image '%{image-version}' --arg kubernetes '%{server-kubernetes-version}' \
      --arg containerd '%{server-containerd-version}' \
      --arg khash '%{server-kubernetes-sha256}' --arg chash '%{server-containerd-sha256}' \
      --arg pause '%{server-pause-image}' --arg baseline "${baseline}" \
      --arg console "$(jq -r .images.console.ref /platform/platform-lock.json)" --arg health '%{server-health-image}' \
      --arg executor "$(jq -r .images.argoexec.ref /platform/platform-lock.json)" \
      '{schema:1,runtime:{image_version:$image,kubernetes:$kubernetes,containerd:$containerd,
         kubernetes_file:("server-kubernetes_"+$image+".raw"),
         containerd_file:("server-containerd_"+$image+".raw"),
         kubernetes_sha256:$khash,containerd_sha256:$chash},pause_image:$pause,
       baseline_commit:$baseline,console_image:$console,health_image:$health,workflow_executor_image:$executor}' \
      > "${root}/share/bluefin-server/profile.json"
    install -Dm0644 "${root}/share/bluefin-server/profile.json" "%{install-root}/profile.json"
  - "%{sysext-pack}"
