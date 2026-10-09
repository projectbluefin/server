kind: manual
description: |
  shim (rhboot/shim) built from the upstream release tarball with the FSDK
  toolchain, for the enrollment-free Secure Boot path. Only the image's
  `shim` option (project.conf) pulls it into the graph.

  The vendor certificate compiled into shim is the image DB certificate
  (/boot-keys/DB.crt, DER): shim trusts whatever DB signs (systemd-boot, the
  UKIs, MokManager) even on firmware whose db holds only Microsoft's keys,
  once Microsoft signs this shim through shim-review
  (docs/skills/secure-boot-keys.md, "Shim").

  Installs to %{datadir}/bluefin-server/shim/:
    shim<efi-arch>.efi         unsigned: the shim-review submission binary
    shim<efi-arch>.efi.signed  the same, signed with DB, so firmware that
                               trusts the Bluefin keys boots it
    mm<efi-arch>.efi.signed    MokManager, signed with DB (shim checks it
                               against the vendor certificate)

  shim chain-loads DEFAULT_LOADER, systemd-boot at
  \EFI\systemd\systemd-boot<efi-arch>.efi, where the image already lays out
  the DB-signed systemd-boot. The fallback loader (fb<efi-arch>.efi) is not
  shipped: next to BOOT<EFI-ARCH>.EFI it would write firmware boot entries on
  every machine a stick boots, and the installed-disk layout that would need
  it is not wired yet.

build-depends:
- base/base-stack.bst
- freedesktop-sdk.bst:public-stacks/buildsystem-make.bst
- freedesktop-sdk.bst:components/binutils.bst
- freedesktop-sdk.bst:components/openssl.bst
- freedesktop-sdk.bst:components/systemd.bst
- freedesktop-sdk.bst:components/_private/sbsigntools.bst
- bluefin-server/keys/boot-keys.bst

variables:
  shim-version: "16.1"
  strip-binaries: ''
  efi-arch: x64
  # EFI directory name; shim's vendor SBAT file must be data/sbat.<EFIDIR>.csv.
  shim-efidir: bluefin-server
  # shim's own SBAT entry for this build (SBAT.md): component
  # shim.<vendor>, its generation (raise it to revoke every earlier
  # Bluefin Server shim), vendor, package, version, URL.
  shim-sbat: shim.%{shim-efidir},1,Bluefin Server,shim,%{shim-version},https://github.com/projectbluefin/server
  shim-default-loader: \EFI\systemd\systemd-boot%{efi-arch}.efi
  shim-dir: "%{datadir}/bluefin-server/shim"
  (?):
  - arch == "aarch64":
      efi-arch: aa64

config:
  configure-commands:
  - |
    set -eu
    # Baseline x86_64 only for now; the aarch64 build axis is roadmap work.
    if [ "%{arch}" != x86_64 ]; then
      echo "ERROR: shim is only built for x86_64 (arch=%{arch})" >&2
      exit 1
    fi
    # shim names the build host "buildhost" (no uname) when it is set.
    : "${SOURCE_DATE_EPOCH:?shim needs SOURCE_DATE_EPOCH for a reproducible build}"
    openssl x509 -in /boot-keys/DB.crt -outform DER -out vendor.cer
    printf '%s\n' '%{shim-sbat}' > 'data/sbat.%{shim-efidir}.csv'

  build-commands:
  # The FSDK build environment's CFLAGS/LDFLAGS are for userspace; shim and
  # its bundled gnu-efi set their own freestanding flags. binutils 2.46 reads
  # objcopy's --target as input and output target; the PE conversion needs
  # --output-target (freedesktop-sdk patches shim's Make.defaults the same
  # way). FSDK has no dos2unix; the SBAT file above already has LF endings.
  # -j1: freedesktop-sdk's own shim build runs serially too. DEFAULT_LOADER
  # lands in a C string literal, so each backslash is doubled.
  - |
    set -eu
    unset CFLAGS CPPFLAGS CXXFLAGS LDFLAGS
    loader="$(printf '%s' '%{shim-default-loader}' | sed 's/\\/\\\\/g')"
    make -j1 \
      VENDOR_CERT_FILE=vendor.cer \
      DEFAULT_LOADER="${loader}" \
      EFIDIR='%{shim-efidir}' \
      FORMAT='--output-target efi-app-%{arch}' \
      DOS2UNIX=cp D2UFLAGS= \
      shim%{efi-arch}.efi mm%{efi-arch}.efi

  install-commands:
  - |
    set -eu
    dst="%{install-root}%{shim-dir}"
    install -Dm644 shim%{efi-arch}.efi "${dst}/shim%{efi-arch}.efi"
    # systemd-sbsign, unlike sbsign, takes the signing time from
    # SOURCE_DATE_EPOCH, so the signatures are reproducible.
    for f in shim%{efi-arch}.efi mm%{efi-arch}.efi; do
      %{indep-libdir}/systemd/systemd-sbsign sign \
        --private-key=/boot-keys/DB.key --certificate=/boot-keys/DB.crt \
        --output="${dst}/${f}.signed" "${f}"
      sbverify --cert /boot-keys/DB.crt "${dst}/${f}.signed"
    done

  # Fail the build unless the binaries carry what shim-review and the boot
  # chain rely on.
  - |
    set -eu
    shim="%{install-root}%{shim-dir}/shim%{efi-arch}.efi"
    # .vendor_cert: shim's cert_table (four 32-bit fields: authorized size,
    # deauthorized size, their offsets), then the authorized certificate.
    objcopy -O binary -j .vendor_cert "${shim}" vendor_cert.bin
    n="$(stat -c %s vendor.cer)"
    size="$(od -An -tu4 -N4 vendor_cert.bin | tr -d ' ')"
    if [ "${size}" != "${n}" ] || ! cmp -s -n "${n}" -i 16:0 vendor_cert.bin vendor.cer; then
      echo "ERROR: ${shim}: .vendor_cert does not hold the DB certificate" >&2
      exit 1
    fi
    # .sbat: shim and MokManager both carry the Bluefin Server entry.
    for f in "${shim}" mm%{efi-arch}.efi; do
      objcopy -O binary -j .sbat "${f}" sbat.bin
      tr -d '\0' < sbat.bin > sbat.csv
      cat sbat.csv
      if ! grep -Fxq '%{shim-sbat}' sbat.csv; then
        echo "ERROR: ${f}: .sbat lacks '%{shim-sbat}'" >&2
        exit 1
      fi
    done
    # DEFAULT_LOADER, as the UTF-16 path shim loads.
    if ! strings -el "${shim}" | grep -Fxq '%{shim-default-loader}'; then
      echo "ERROR: ${shim}: DEFAULT_LOADER is not %{shim-default-loader}" >&2
      exit 1
    fi
    sha256sum "${shim}"

sources:
- kind: tar
  url: github:rhboot/shim/releases/download/%{shim-version}/shim-%{shim-version}.tar.bz2
  ref: 46319cd228d8f2c06c744241c0f342412329a7c630436fce7f82cf6936b1d603
