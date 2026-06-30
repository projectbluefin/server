kind: script

build-depends:
  - freedesktop-sdk.bst:components/oci-builder.bst
  - static/static-init-script.bst
  - filename: static/static-runtime.bst
    config:
      location: /layer

config:
  commands:
    - |
      set -eu
      L=/layer

      # --- distroless: remove shells (runtime domain, not the 'shells' split) ---
      rm -f  "$L"/usr/bin/bash "$L"/usr/bin/sh "$L"/bin/bash "$L"/bin/sh "$L"/usr/bin/bashbug
      rm -rf "$L"/usr/lib/bash "$L"/usr/lib/*/bash

      # --- terminfo: useless in containers ---
      rm -rf "$L"/usr/share/terminfo "$L"/usr/share/tabset \
             "$L"/etc/terminfo "$L"/lib/terminfo

      # --- gcc dev/debug runtimes: sanitizers + fortran, never used at runtime ---
      rm -f "$L"/usr/lib/*/libasan.so*  "$L"/usr/lib/*/libtsan.so* \
            "$L"/usr/lib/*/liblsan.so*  "$L"/usr/lib/*/libubsan.so* \
            "$L"/usr/lib/*/libhwasan.so* "$L"/usr/lib/*/libgfortran.so*

      # --- build-time tools leaked into runtime domain ---
      rm -f "$L"/usr/bin/localedef "$L"/usr/bin/iconvconfig

    - |
      if [ -d /initial_scripts ]; then
        for i in /initial_scripts/*; do
          "${i}" /layer
        done
      fi

    - |
      cd "%{install-root}"
      build-oci <<EOF
      mode: oci
      gzip: disabled
      images:
      - os: linux
        architecture: "%{go-arch}"
        layer: /layer
        comment: "fsdk-containers static image"
        config:
          Labels:
            'org.opencontainers.image.title': 'static'
            'org.opencontainers.image.description': 'Distroless static image carved from freedesktop-sdk — no glibc, for statically compiled binaries'
            'org.opencontainers.image.vendor': 'Project Bluefin'
            'org.opencontainers.image.licenses': 'Apache-2.0'
            'org.opencontainers.image.url': 'https://github.com/projectbluefin/fsdk-containers'
            'org.opencontainers.image.source': 'https://github.com/projectbluefin/fsdk-containers'
            'io.artifacthub.package.readme-url': 'https://raw.githubusercontent.com/projectbluefin/fsdk-containers/main/README.md'
            'io.artifacthub.package.logo-url': 'https://projectbluefin.io/logo.png'
            'io.artifacthub.package.license': 'Apache-2.0'
            'io.artifacthub.package.maintainers': '[{"name":"Project Bluefin","email":"maintainers@projectbluefin.io"}]'
            'io.artifacthub.package.keywords': 'distroless,freedesktop-sdk,bluefin,static'
            'io.artifacthub.package.category': 'integration-delivery'
        index-annotations:
          'org.opencontainers.image.ref.name': 'ghcr.io/projectbluefin/static:latest'
      EOF
