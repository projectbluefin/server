kind: script

build-depends:
  - freedesktop-sdk.bst:components/oci-builder.bst
  - base/base-init-script.bst
  - filename: base/base-runtime.bst
    config:
      location: /layer

config:
  commands:
    # ---------------------------------------------------------------------
    # SLIM RECIPE (shared, reusable across every fsdk-containers image).
    #
    # FSDK split-rule domains only cover devel/debug/doc/sysconf/tests/
    # shells/static-blocklist/license/locale/vm-only/zoneinfo. They do NOT
    # cover the largest runtime-domain bloat (terminfo, gconv charset
    # modules, gcc sanitizer/fortran runtimes, glibc locale-archive,
    # build-time tools). Those are removed explicitly here, same pattern as
    # the bash removal. Cuts the base rootfs roughly in half (~73M -> ~45M)
    # with no impact on runtime behaviour.
    #
    # Deliberately KEPT (cheap crash-preventers, do not remove):
    #   - tzdata (/usr/share/zoneinfo, ~2.6M): python zoneinfo crashes without it
    #   - common gconv charsets (UTF-*, ISO-8859-1/15, CP1252): legacy decode
    #   - ca-certificates + /usr/share/pki trust source
    #   - libstdc++, libgcc_s, libgomp (C++/OpenMP runtimes apps may link)
    # ---------------------------------------------------------------------
    - |
      set -eu
      L=/layer

      # --- distroless: remove shells (runtime domain, not the 'shells' split) ---
      rm -f  "$L"/usr/bin/bash "$L"/usr/bin/sh "$L"/bin/bash "$L"/bin/sh "$L"/usr/bin/bashbug
      rm -rf "$L"/usr/lib/bash "$L"/usr/lib/*/bash

      # --- terminfo: ~12M terminal capability DB, useless in containers ---
      rm -rf "$L"/usr/share/terminfo "$L"/usr/share/tabset \
             "$L"/etc/terminfo "$L"/lib/terminfo

      # --- gcc dev/debug runtimes: sanitizers + fortran, never used at runtime (~9M) ---
      rm -f "$L"/usr/lib/*/libasan.so*  "$L"/usr/lib/*/libtsan.so* \
            "$L"/usr/lib/*/liblsan.so*  "$L"/usr/lib/*/libubsan.so* \
            "$L"/usr/lib/*/libhwasan.so* "$L"/usr/lib/*/libgfortran.so*

      # --- gconv: keep common charsets, drop the long tail (~7M) ---
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

      # --- glibc locale-archive: drop to built-in C.UTF-8 only (~3M) ---
      rm -f  "$L"/usr/lib/locale/locale-archive
      rm -rf "$L"/usr/share/i18n/charmaps

      # --- build-time tools leaked into the runtime domain ---
      rm -f "$L"/usr/bin/localedef "$L"/usr/bin/sln "$L"/usr/bin/iconvconfig \
            "$L"/usr/bin/ldconfig "$L"/usr/sbin/ldconfig \
            "$L"/usr/bin/pcre2test "$L"/usr/bin/pcre2grep

      # --- extra PCRE2 code-unit widths (keep the 8-bit lib) ---
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
        comment: "fsdk-containers base image"
        config:
          Labels:
            'org.opencontainers.image.title': 'base'
            'org.opencontainers.image.description': 'Distroless base image carved from freedesktop-sdk'
            'org.opencontainers.image.vendor': 'Project Bluefin'
            'org.opencontainers.image.licenses': 'Apache-2.0'
            'org.opencontainers.image.url': 'https://github.com/projectbluefin/fsdk-containers'
            'org.opencontainers.image.source': 'https://github.com/projectbluefin/fsdk-containers'
            'io.artifacthub.package.readme-url': 'https://raw.githubusercontent.com/projectbluefin/fsdk-containers/main/README.md'
            'io.artifacthub.package.logo-url': 'https://projectbluefin.io/logo.png'
            'io.artifacthub.package.license': 'Apache-2.0'
            'io.artifacthub.package.maintainers': '[{"name":"Project Bluefin","email":"maintainers@projectbluefin.io"}]'
            'io.artifacthub.package.keywords': 'distroless,freedesktop-sdk,bluefin'
            'io.artifacthub.package.category': 'integration-delivery'
        index-annotations:
          'org.opencontainers.image.ref.name': 'ghcr.io/projectbluefin/base:latest'
      EOF
