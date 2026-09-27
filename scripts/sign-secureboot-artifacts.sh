#!/usr/bin/env bash
# Secure Boot signing pass over the exported installer/UKI artifacts in dist/.
#
# BuildStream builds are hermetic, so the signing key cannot enter the element
# graph; this runs in CI after `just export-pxe`, the same way SHA256SUMS is
# GPG-signed after the build. Every Authenticode payload a Secure Boot machine
# will execute is signed with one project db key:
#
#   1. the target OS UKI  (dist/bluefin-server-<flatcar-version>.efi)
#   2. systemd-boot and the target UKI *inside* the installer initrd
#      (dist/bluefin-server-pxe-initrd-*.cpio.gz), which is where the installer
#      takes them from when it populates the target ESP
#   3. the installer UKI on the installer media ESP (EFI/BOOT/BOOTX64.EFI),
#      rebuilt from its own .linux/.cmdline sections plus the initrd from (2)
#   4. the PXE kernel (dist/bluefin-server-pxe-vmlinuz-*), replacing the
#      Flatcar development signature no stock firmware trusts
#
# The initrd is not unpacked: the kernel accepts concatenated (individually
# compressed) cpio archives and later members overwrite earlier ones, so the
# signed files travel in a small root-owned overlay cpio appended to the
# original. The signing certificate is published next to the artifacts
# (bluefin-server-secureboot.der / .pem) and on the installer media ESP so
# operators and PXE servers can enrol it in the firmware db.
#
# Inputs (environment):
#   SECUREBOOT_SIGNING_KEY   PEM RSA private key (required)
#   SECUREBOOT_SIGNING_CERT  PEM X.509 certificate for that key (required)
#   DIST                     artifact directory (default: dist)
#
# Tools: sbsign sbverify sbattach ukify objcopy mcopy sfdisk jq zstd cpio gzip openssl
set -euo pipefail

DIST="${DIST:-dist}"
TARGET_UKI_PATH="usr/lib/bluefin-server/bluefin-server.efi"
SD_BOOT_PATH="usr/lib/systemd/boot/efi/systemd-bootx64.efi"
INSTALLER_UKI_ESP_PATH="EFI/BOOT/BOOTX64.EFI"
CERT_BASENAME="bluefin-server-secureboot"
ESP_PARTTYPE="C12A7328-F81F-11D2-BA4B-00A0C93EC93B"
# BuildStream compresses the installer image with this level; keep the
# re-signed image byte-comparable in size.
ZSTD_LEVEL=19

die() { echo "ERROR: $*" >&2; exit 1; }

[ -n "${SECUREBOOT_SIGNING_KEY:-}" ] || die "SECUREBOOT_SIGNING_KEY is not set"
[ -n "${SECUREBOOT_SIGNING_CERT:-}" ] || die "SECUREBOOT_SIGNING_CERT is not set"
for tool in sbsign sbverify sbattach ukify objcopy mcopy sfdisk jq zstd cpio gzip openssl; do
  command -v "${tool}" >/dev/null 2>&1 || die "required tool '${tool}' is not installed"
done

# Exactly one of each artifact must be present; refuse to guess otherwise.
one_file() {
  local pattern="$1" matches
  mapfile -t matches < <(find "${DIST}" -maxdepth 1 -type f -name "${pattern}" | sort)
  [ "${#matches[@]}" -eq 1 ] || die "expected exactly one ${DIST}/${pattern}, found ${#matches[@]}"
  printf '%s\n' "${matches[0]}"
}
TARGET_UKI="$(one_file 'bluefin-server-[0-9]*.efi')"
PXE_INITRD="$(one_file 'bluefin-server-pxe-initrd-*.cpio.gz')"
PXE_VMLINUZ="$(one_file 'bluefin-server-pxe-vmlinuz-*')"
INSTALLER_ZST="$(one_file 'bluefin-server-installer-*.raw.zst')"

WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT
umask 077
KEY="${WORK}/db.key"
CERT="${WORK}/db.pem"
printf '%s\n' "${SECUREBOOT_SIGNING_KEY}" > "${KEY}"
printf '%s\n' "${SECUREBOOT_SIGNING_CERT}" > "${CERT}"
umask 022
openssl x509 -in "${CERT}" -noout -subject -enddate

sign_pe() {
  local in="$1" out="$2"
  sbsign --key "${KEY}" --cert "${CERT}" --output "${out}" "${in}"
  sbverify --cert "${CERT}" "${out}"
}

# 1. Target OS UKI (published for GitHub Releases and systemd-sysupdate).
echo "==> Signing target UKI ${TARGET_UKI}"
sign_pe "${TARGET_UKI}" "${WORK}/target.efi"
mv "${WORK}/target.efi" "${TARGET_UKI}"

# 2. Installer initrd overlay: signed target UKI + signed systemd-boot.
echo "==> Signing systemd-boot and target UKI inside ${PXE_INITRD}"
OVERLAY="${WORK}/overlay"
mkdir -p "${OVERLAY}/$(dirname "${TARGET_UKI_PATH}")" "${OVERLAY}/$(dirname "${SD_BOOT_PATH}")"
cp "${TARGET_UKI}" "${OVERLAY}/${TARGET_UKI_PATH}"
# The element packs the initrd with `find .`, so members are named ./usr/...;
# GNU cpio may list them with or without the ./ prefix. Listing the member
# and extracting only it failing means the initrd layout changed and bootctl
# would install an unsigned loader.
INITRD_MEMBERS="$(gzip -dc "${PXE_INITRD}" | cpio --quiet -t)"
grep -qxE "(\./)?${SD_BOOT_PATH}" <<< "${INITRD_MEMBERS}" \
  || die "${SD_BOOT_PATH} is not in ${PXE_INITRD}"
PXE_INITRD_ABS="$(realpath "${PXE_INITRD}")"
( cd "${WORK}" && gzip -dc "${PXE_INITRD_ABS}" \
    | cpio --quiet -i --make-directories --no-absolute-filenames --no-preserve-owner \
        "${SD_BOOT_PATH}" "./${SD_BOOT_PATH}" )
[ -s "${WORK}/${SD_BOOT_PATH}" ] || die "failed to extract ${SD_BOOT_PATH} from ${PXE_INITRD}"
sign_pe "${WORK}/${SD_BOOT_PATH}" "${OVERLAY}/${SD_BOOT_PATH}"
chmod 0755 "${OVERLAY}/${TARGET_UKI_PATH}" "${OVERLAY}/${SD_BOOT_PATH}"
( cd "${OVERLAY}" && find . -print0 \
    | cpio --quiet --null --create --format=newc --owner=root:root --reproducible ) \
  | gzip -9 -c > "${WORK}/overlay.cpio.gz"
cat "${PXE_INITRD}" "${WORK}/overlay.cpio.gz" > "${WORK}/initrd.cpio.gz"
mv "${WORK}/initrd.cpio.gz" "${PXE_INITRD}"

# 3. Installer UKI on the installer media ESP.
echo "==> Re-signing installer UKI inside ${INSTALLER_ZST}"
RAW="${WORK}/installer.raw"
zstd -d -q "${INSTALLER_ZST}" -o "${RAW}"
ESP_JSON="$(sfdisk --json "${RAW}")"
SECTOR_SIZE="$(jq -r '.partitiontable.sectorsize' <<< "${ESP_JSON}")"
ESP_START="$(jq -r --arg t "${ESP_PARTTYPE}" \
  '[.partitiontable.partitions[] | select((.type | ascii_upcase) == $t)] | if length == 1 then .[0].start else empty end' \
  <<< "${ESP_JSON}")"
[ -n "${ESP_START}" ] || die "could not find exactly one ESP partition in ${RAW}"
ESP_IMG="${RAW}@@$((ESP_START * SECTOR_SIZE))"
export MTOOLS_SKIP_CHECK=1
mcopy -n -i "${ESP_IMG}" "::${INSTALLER_UKI_ESP_PATH}" "${WORK}/installer-orig.efi"
# Reuse the built UKI's own kernel, command line and os-release so the only
# things that change are the initrd (now carrying signed payloads) and the
# signature; ukify would otherwise take .osrel from the CI host.
dump_section() {
  objcopy -O binary --only-section="$1" "${WORK}/installer-orig.efi" "$2"
}
dump_section .linux "${WORK}/installer.linux"
dump_section .cmdline "${WORK}/installer.cmdline.raw"
dump_section .osrel "${WORK}/installer.osrel.raw"
INSTALLER_CMDLINE="$(tr -d '\0' < "${WORK}/installer.cmdline.raw")"
tr -d '\0' < "${WORK}/installer.osrel.raw" > "${WORK}/installer.osrel"
[ -s "${WORK}/installer.linux" ] || die "installer UKI has no .linux section"
[ -n "${INSTALLER_CMDLINE}" ] || die "installer UKI has no .cmdline section"
[ -s "${WORK}/installer.osrel" ] || die "installer UKI has no .osrel section"
ukify build \
  --linux="${WORK}/installer.linux" \
  --initrd="${PXE_INITRD}" \
  --cmdline="${INSTALLER_CMDLINE}" \
  --os-release="@${WORK}/installer.osrel" \
  --secureboot-private-key="${KEY}" \
  --secureboot-certificate="${CERT}" \
  --output="${WORK}/installer-signed.efi"
sbverify --cert "${CERT}" "${WORK}/installer-signed.efi"
openssl x509 -in "${CERT}" -outform DER -out "${WORK}/${CERT_BASENAME}.der"
mcopy -o -i "${ESP_IMG}" "${WORK}/installer-signed.efi" "::${INSTALLER_UKI_ESP_PATH}"
mcopy -o -i "${ESP_IMG}" "${WORK}/${CERT_BASENAME}.der" "::${CERT_BASENAME}.der"
zstd --rm -T0 "-${ZSTD_LEVEL}" -q -f "${RAW}" -o "${INSTALLER_ZST}"

# 4. PXE kernel: replace Flatcar's development signature with the project key.
# sbsign would append a second signature; strip the existing table first so
# the published kernel carries only the project signature.
echo "==> Re-signing PXE kernel ${PXE_VMLINUZ}"
cp "${PXE_VMLINUZ}" "${WORK}/vmlinuz.unsigned"
if sbverify --list "${WORK}/vmlinuz.unsigned" >/dev/null 2>&1; then
  sbattach --remove "${WORK}/vmlinuz.unsigned"
fi
sign_pe "${WORK}/vmlinuz.unsigned" "${WORK}/vmlinuz.signed"
mv "${WORK}/vmlinuz.signed" "${PXE_VMLINUZ}"

# Publish the certificate for db enrolment (DER for firmware/PXE, PEM for tooling).
cp "${WORK}/${CERT_BASENAME}.der" "${DIST}/${CERT_BASENAME}.der"
cp "${CERT}" "${DIST}/${CERT_BASENAME}.pem"
chmod 0644 "${DIST}/${CERT_BASENAME}.der" "${DIST}/${CERT_BASENAME}.pem"

echo "==> Secure Boot signing complete:"
ls -lh "${TARGET_UKI}" "${PXE_INITRD}" "${PXE_VMLINUZ}" "${INSTALLER_ZST}" \
  "${DIST}/${CERT_BASENAME}.der" "${DIST}/${CERT_BASENAME}.pem"
