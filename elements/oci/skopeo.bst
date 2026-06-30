kind: script

build-depends:
  - freedesktop-sdk.bst:components/oci-builder.bst
  - base/base-init-script.bst
  - filename: skopeo/skopeo-runtime.bst
    config:
      location: /layer

config:
  commands:
    - |
      set -eu
      L=/layer

      # Apply SLIM recipe (same as base image)
      rm -f  "$L"/usr/bin/bash "$L"/usr/bin/sh "$L"/bin/bash "$L"/bin/sh "$L"/usr/bin/bashbug
      rm -rf "$L"/usr/lib/bash "$L"/usr/lib/*/bash

      rm -rf "$L"/usr/share/terminfo "$L"/usr/share/tabset \
             "$L"/etc/terminfo "$L"/lib/terminfo

      rm -f "$L"/usr/lib/*/libasan.so*  "$L"/usr/lib/*/libtsan.so* \
            "$L"/usr/lib/*/liblsan.so*  "$L"/usr/lib/*/libubsan.so* \
            "$L"/usr/lib/*/libhwasan.so* "$L"/usr/lib/*/libgfortran.so*

      for g in "$L"/usr/lib/*/gconv; do
        [ -d "$g" ] || continue
        for f in "$g"/*; do
          [ -f "$f" ] || continue
          case "${f##*/}" in
            gconv-modules*|UTF*|UNICODE*|ISO8859-1.so|ISO8859-15.so|CP1252.so|ANSI_X3.110.so) : ;;
            *) rm -f "$f" ;;
          esac
        done
      done

      rm -f  "$L"/usr/lib/locale/locale-archive
      rm -rf "$L"/usr/share/i18n/charmaps

      rm -f "$L"/usr/bin/localedef "$L"/usr/bin/sln "$L"/usr/bin/iconvconfig \
            "$L"/usr/bin/ldconfig "$L"/usr/sbin/ldconfig \
            "$L"/usr/bin/pcre2test "$L"/usr/bin/pcre2grep

      rm -f "$L"/usr/lib/*/libpcre2-16.so* "$L"/usr/lib/*/libpcre2-32.so* \
            "$L"/usr/lib/*/libpcre2-posix.so*

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
        comment: "fsdk-containers skopeo image"
        config:
          Labels:
            'org.opencontainers.image.title': 'skopeo'
            'org.opencontainers.image.description': 'Distroless skopeo image carved from freedesktop-sdk'
            'org.opencontainers.image.vendor': 'Project Bluefin'
            'org.opencontainers.image.licenses': 'Apache-2.0'
            'org.opencontainers.image.url': 'https://github.com/projectbluefin/fsdk-containers'
            'org.opencontainers.image.source': 'https://github.com/projectbluefin/fsdk-containers'
            'io.artifacthub.package.readme-url': 'https://raw.githubusercontent.com/projectbluefin/fsdk-containers/main/README.md'
            'io.artifacthub.package.logo-url': 'https://projectbluefin.io/logo.png'
            'io.artifacthub.package.license': 'Apache-2.0'
            'io.artifacthub.package.maintainers': '[{"name":"Project Bluefin","email":"maintainers@projectbluefin.io"}]'
            'io.artifacthub.package.keywords': 'distroless,freedesktop-sdk,bluefin,skopeo'
            'io.artifacthub.package.category': 'integration-delivery'
        index-annotations:
          'org.opencontainers.image.ref.name': 'ghcr.io/projectbluefin/skopeo:latest'
      EOF
