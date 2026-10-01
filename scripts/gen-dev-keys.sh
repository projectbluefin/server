#!/usr/bin/env bash
# Generate a local, throwaway Secure Boot + kernel module signing key set
# under files/boot-keys/ (gitignored). Dogfood builds sign the UKI and
# systemd-boot with DB and kernel modules with linux-module-cert; the
# firmware enrolls PK/KEK/DB from the ESP on first boot.
#
# Layout (matches freedesktop-sdk's files/boot-keys convention):
#   files/boot-keys/{PK,KEK,DB}.{key,crt}
#   files/boot-keys/linux-module-cert.key         private, never staged into the kernel build
#   files/boot-keys/modules/linux-module-cert.crt public, baked into the kernel's trusted keyring
#   files/boot-keys/sysupdate-signing.asc         OpenPGP secret key that signs SHA256SUMS
#   files/boot-keys/import-pubring.pgp            its public keyring, installed as
#                                                 /usr/lib/systemd/import-pubring.pgp (importd, sysupdate)
#
# Existing keys are never overwritten without --force: every key is baked
# into or signs the image, so replacing one needs a new image-version (see
# "Keys" in docs/skills/ddi-installer-build.md), and changing
# modules/linux-module-cert.crt also forces a kernel rebuild. A partial set
# (some files of a pair or of the boot set missing) is an error rather than
# something to fill in, since filling it in would replace the files that do
# exist.
set -euo pipefail

dir="$(cd "$(dirname "$0")/.." && pwd)/files/boot-keys"
force=0
[ "${1:-}" = "--force" ] && force=1

mkdir -p "${dir}/modules"
chmod 0700 "${dir}"
umask 077
owner="${USER:-dev}@$(hostname -s 2>/dev/null || echo localhost)"

gen_signing_key() {
    local home
    home="$(mktemp -d)"
    GNUPGHOME="${home}" gpg --batch --quiet --passphrase '' \
        --quick-gen-key "Bluefin Server dev image signing (${owner})" rsa3072 sign never
    GNUPGHOME="${home}" gpg --batch --armor --export-secret-keys > "${dir}/sysupdate-signing.asc"
    GNUPGHOME="${home}" gpg --batch --export > "${dir}/import-pubring.pgp"
    chmod 0644 "${dir}/import-pubring.pgp"
    rm -rf "${home}"
    echo "Generated image signing key in ${dir}"
}

signing_keys=(sysupdate-signing.asc import-pubring.pgp)
boot_keys=(PK.key PK.crt KEK.key KEK.crt DB.key DB.crt linux-module-cert.key modules/linux-module-cert.crt)

# Prints "none", "all" or "partial" for the named files under ${dir}.
key_set_state() {
    local present=0 f
    for f in "$@"; do
        [ -s "${dir}/${f}" ] && present=$((present + 1))
    done
    if [ "${present}" = 0 ]; then echo none
    elif [ "${present}" = "$#" ]; then echo all
    else echo partial
    fi
}

signing_state="$(key_set_state "${signing_keys[@]}")"
boot_state="$(key_set_state "${boot_keys[@]}")"
if [ "${force}" = 0 ]; then
    for state in "signing:${signing_state}" "boot:${boot_state}"; do
        if [ "${state#*:}" = partial ]; then
            echo "ERROR: ${dir} holds a partial ${state%%:*} key set; refusing to overwrite the files that exist." >&2
            echo "       Restore the missing files, or pass --force to regenerate every key (then bump image-version)." >&2
            exit 1
        fi
    done
fi

if [ "${signing_state}" != all ] || [ "${force}" = 1 ]; then
    gen_signing_key
fi

if [ "${boot_state}" = all ] && [ "${force}" = 0 ]; then
    echo "Keys already exist in ${dir}; pass --force to regenerate (rebuilds the kernel)."
    exit 0
fi

for name in PK KEK DB; do
    openssl req -new -x509 -newkey rsa:2048 -nodes -sha256 -days 3650 \
        -subj "/CN=Bluefin Server dev ${name} (${owner})/" \
        -keyout "${dir}/${name}.key" -out "${dir}/${name}.crt" 2>/dev/null
done

openssl req -new -x509 -newkey rsa:4096 -nodes -sha512 -days 3650 \
    -subj "/CN=Bluefin Server dev kernel modules (${owner})/" \
    -addext "keyUsage=digitalSignature" \
    -addext "extendedKeyUsage=codeSigning" \
    -keyout "${dir}/linux-module-cert.key" -out "${dir}/modules/linux-module-cert.crt" 2>/dev/null

chmod 0644 "${dir}"/*.crt "${dir}/modules/linux-module-cert.crt"
echo "Generated dev keys in ${dir}"
