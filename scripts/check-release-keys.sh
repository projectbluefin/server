#!/usr/bin/env bash
# Refuse a release key set that carries the committed INSECURE dev module key
# (files/dev-keys/, published so that non-release builds share one kernel
# cache key). A release kernel trusting that certificate would load any module
# anyone signs with the public key; a release signed with that key would ship
# modules only dev kernels accept.
#
#   check-release-keys.sh [KEY_DIR]    (default: files/boot-keys)
#
# Compares public keys, so a certificate re-issued for the dev key is caught
# too. The module key is checked when KEY_DIR has one (release builds); the
# kernel cache seed stages only the certificate.
set -euo pipefail

cd "$(dirname "$0")/.."
dir="${1:-files/boot-keys}"
dev_cert=files/dev-keys/INSECURE-dev-module-key.crt

die() { echo "check-release-keys: $*" >&2; exit 1; }

dev_pub="$(openssl x509 -in "${dev_cert}" -noout -pubkey)" || die "cannot read ${dev_cert}"
cert="${dir}/modules/linux-module-cert.crt"
[ -s "${cert}" ] || die "missing ${cert}"
cert_pub="$(openssl x509 -in "${cert}" -noout -pubkey 2>/dev/null)" || die "${cert} is not a certificate"
[ "${cert_pub}" != "${dev_pub}" ] \
    || die "${cert} is the INSECURE dev module certificate; release builds must never trust it"

key="${dir}/linux-module-cert.key"
if [ -e "${key}" ]; then
    key_pub="$(openssl pkey -in "${key}" -pubout 2>/dev/null)" || die "${key} is not a private key"
    [ "${key_pub}" != "${dev_pub}" ] \
        || die "${key} is the INSECURE dev module key; release builds must never sign with it"
fi
echo "check-release-keys: the module certificate and key in ${dir} are not the dev pair"
