# shellcheck shell=bash
# Sourced by the QEMU checks that boot one machine through UEFI
# (dogfood-diskless.sh, dogfood-installer.sh, dogfood-homelab-installer.sh):
# where the OVMF firmware is. Each prints a path, from its environment
# variable when set, else the first of the distributions' usual files;
# with neither it fails and says which variable to set.
#
#   ovmf_code            Secure Boot firmware code   (OVMF_CODE)
#   ovmf_code_insecure   firmware without Secure Boot (OVMF_CODE_INSECURE)
#   ovmf_vars            blank variable store         (OVMF_VARS)

first_existing() { for f in "$@"; do [ -f "$f" ] && { echo "$f"; return 0; }; done; return 1; }

ovmf_code() {
    [ -n "${OVMF_CODE:-}" ] && { echo "${OVMF_CODE}"; return 0; }
    first_existing \
        /usr/share/edk2/ovmf/OVMF_CODE.secboot.fd \
        /usr/share/OVMF/OVMF_CODE_4M.secboot.fd \
        /usr/share/OVMF/OVMF_CODE.secboot.fd \
        /usr/share/edk2/x64/OVMF_CODE.secboot.4m.fd \
        || { echo "ERROR: no Secure Boot OVMF_CODE found (set OVMF_CODE)" >&2; return 1; }
}

ovmf_code_insecure() {
    [ -n "${OVMF_CODE_INSECURE:-}" ] && { echo "${OVMF_CODE_INSECURE}"; return 0; }
    first_existing \
        /usr/share/edk2/ovmf/OVMF_CODE.fd \
        /usr/share/OVMF/OVMF_CODE_4M.fd \
        /usr/share/OVMF/OVMF_CODE.fd \
        /usr/share/edk2/x64/OVMF_CODE.4m.fd \
        || { echo "ERROR: no OVMF_CODE without Secure Boot found (set OVMF_CODE_INSECURE)" >&2; return 1; }
}

ovmf_vars() {
    [ -n "${OVMF_VARS:-}" ] && { echo "${OVMF_VARS}"; return 0; }
    first_existing \
        /usr/share/edk2/ovmf/OVMF_VARS.fd \
        /usr/share/OVMF/OVMF_VARS_4M.fd \
        /usr/share/OVMF/OVMF_VARS.fd \
        /usr/share/edk2/x64/OVMF_VARS.4m.fd \
        || { echo "ERROR: no blank OVMF_VARS found (set OVMF_VARS)" >&2; return 1; }
}
