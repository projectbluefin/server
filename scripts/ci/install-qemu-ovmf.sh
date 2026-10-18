#!/usr/bin/env bash
# Install what the boot test runs on an Ubuntu runner: QEMU, the disk tools
# the dogfood scripts call, and Fedora's Secure Boot OVMF, then export
# OVMF_CODE, OVMF_CODE_INSECURE and OVMF_VARS to the job's later steps.
# boot-test and boot-test-preflight both run this, so they cannot drift.
#
#   bash scripts/ci/install-qemu-ovmf.sh
#
# Ubuntu's OVMF (2025.11) rejects systemd-boot's PK enrollment with
# "Security violation", so the guests kept booting in setup mode with nothing
# verified. Use Fedora's edk2 build, pinned by checksum, which enrolls the
# keys; dogfood-diskless.sh fails if Secure Boot is off. Bumped by hand:
# Renovate cannot move the URL and its checksum together (see ci-tooling.md).
set -euo pipefail

OVMF_RPM_URL=https://kojipkgs.fedoraproject.org/packages/edk2/20260508/6.fc44/noarch/edk2-ovmf-20260508-6.fc44.noarch.rpm
OVMF_RPM_SHA256=8b157ab2aa0cccccf021f43011308349147c76ae59550f52239ea50678dd0a5f

sudo apt-get update
sudo apt-get install -y --no-install-recommends qemu-system-x86 libarchive-tools \
  fdisk dosfstools e2fsprogs mtools
sudo chmod 666 /dev/kvm

rpm="${RUNNER_TEMP:?}/edk2-ovmf.rpm"
ovmf="${RUNNER_TEMP}/ovmf/usr/share/edk2/ovmf"
curl -fsSL --retry 3 -o "${rpm}" "${OVMF_RPM_URL}"
echo "${OVMF_RPM_SHA256}  ${rpm}" | sha256sum -c -
mkdir -p "${RUNNER_TEMP}/ovmf"
bsdtar -xf "${rpm}" -C "${RUNNER_TEMP}/ovmf" \
  ./usr/share/edk2/ovmf/OVMF_CODE.secboot.fd ./usr/share/edk2/ovmf/OVMF_VARS.fd \
  ./usr/share/edk2/ovmf/OVMF_CODE.fd
{
  echo "OVMF_CODE=${ovmf}/OVMF_CODE.secboot.fd"
  echo "OVMF_CODE_INSECURE=${ovmf}/OVMF_CODE.fd"
  echo "OVMF_VARS=${ovmf}/OVMF_VARS.fd"
} >> "${GITHUB_ENV:?}"
