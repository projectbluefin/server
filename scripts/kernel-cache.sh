#!/usr/bin/env bash
# Key-free BuildStream cache of FSDK's kernel (and Go), in the project CAS.
#
#   CASD_CLIENT_CERT=<pem> CASD_CLIENT_KEY=<pem> kernel-cache.sh seed release|dev
#
# The kernel is most of a cold build (figures: docs/skills/ci-tooling.md,
# "Build time and caches") and no upstream cache holds it: its cache key
# depends on the module certificate it trusts (the
# linux-module-cert junction override) and on the patches in
# patches/freedesktop-sdk/ that edit its config (0006 kubenet, 0007 watchdog).
# `seed` stages one committed certificate as
# files/boot-keys/modules/linux-module-cert.crt, the only file the kernel's
# linux-module-cert override imports:
#  - release: files/release-keys/linux-module-cert.crt, which release builds
#    also stage, so their kernel keys match. scripts/check-release-keys.sh
#    must pass.
#  - dev: the public files/dev-keys/INSECURE-dev-module-key.crt, which
#    `just gen-dev-keys` uses for pull requests, the nightly build and local
#    builds, so they pull the kernel instead of compiling it. Only the
#    certificate is staged; its private key never enters this graph.
#
# `seed` builds ELEMENTS with a BuildStream config that pushes artifacts and
# sources to the CAS's mTLS endpoint; every build reads them back through the
# anonymous remote that patches/freedesktop-sdk/0001 adds to the junction's
# project.conf (the top-level project.conf remote does not reach junction
# elements such as the kernel). It builds nothing when a remote already
# holds every element (`available`; an element only cached locally still goes
# through `bst build`, which pushes it).
#
# The CAS is publicly readable. What `seed` pushes is key-free by
# construction: the seed job holds no signing secrets, `seed` refuses to
# build if bluefin-server/keys/boot-keys.bst (the only element that stages
# private keys) is anywhere in the graph of ELEMENTS, and it refuses a
# files/boot-keys/modules/ that holds anything but the one certificate (that
# directory's import is pushed with the kernel).
set -euo pipefail

ELEMENTS=(freedesktop-sdk.bst:components/linux.bst freedesktop-sdk.bst:components/go.bst)
KEYS_ELEMENT=bluefin-server/keys/boot-keys.bst
PUSH_URL=https://cache.projectbluefin.io:11002

cd "$(dirname "$0")/.."

# Output and log lines of a `just bst` command, without colours.
bst_show() {
    just bst "$@" 2>&1 | sed 's/\x1b\[[0-9;]*m//g'
}

# A BuildStream user config adding the CAS as a push remote for artifacts
# and sources, authenticated by the client certificate in $1 (a directory
# inside the checkout, which `just bst` mounts at /src).
write_config() {
    local auth="$1" kind
    for kind in artifacts source-caches; do
        cat <<EOF
${kind}:
  servers:
  - url: ${PUSH_URL}
    push: true
    connection-config:
      keepalive-time: 180
      retry-limit: 5
      retry-delay: 1000
      request-timeout: 180
    auth:
      client-cert: /src/${auth}/client.crt
      client-key: /src/${auth}/client.key
EOF
    done
}

# Stage the certificate the kernel of VARIANT trusts, and nothing else.
stage_cert() {
    local variant="$1" src modules=files/boot-keys/modules extra
    case "${variant}" in
        release) src=files/release-keys/linux-module-cert.crt ;;
        dev) src=files/dev-keys/INSECURE-dev-module-key.crt ;;
    esac
    mkdir -p "${modules}"
    install -m 0644 "${src}" "${modules}/linux-module-cert.crt"
    extra="$(find "${modules}" -mindepth 1 ! -path "${modules}/linux-module-cert.crt")"
    if [ -n "${extra}" ] || grep -q 'PRIVATE KEY' "${modules}/linux-module-cert.crt"; then
        echo "kernel-cache: ${modules} must hold only the certificate; refusing to publish:" >&2
        printf '%s\n' "${extra}" >&2
        exit 1
    fi
    if [ "${variant}" = release ]; then
        bash scripts/check-release-keys.sh
    fi
}

# The credentials directory; global, as the EXIT trap removes it after seed
# returns.
auth=""

seed() {
    local variant="$1" states available
    : "${CASD_CLIENT_CERT:?kernel-cache: CASD_CLIENT_CERT is not set}"
    : "${CASD_CLIENT_KEY:?kernel-cache: CASD_CLIENT_KEY is not set}"
    stage_cert "${variant}"
    if bst_show show --deps all --format "'%{name}'" "${ELEMENTS[@]}" | grep -qxF "${KEYS_ELEMENT}"; then
        echo "kernel-cache: ${KEYS_ELEMENT} is in the graph of ${ELEMENTS[*]}; refusing to publish" >&2
        exit 1
    fi
    auth="$(umask 077 && mktemp -d .casd.XXXXXX)"
    trap 'rm -rf "${auth}"' EXIT
    (
        umask 077
        printf '%s\n' "${CASD_CLIENT_CERT}" > "${auth}/client.crt"
        printf '%s\n' "${CASD_CLIENT_KEY}" > "${auth}/client.key"
    )
    write_config "${auth}" > "${auth}/buildstream.conf"
    export BST_FLAGS="${BST_FLAGS:-} --config /src/${auth}/buildstream.conf"
    # BuildStream only warns about a remote it cannot reach (a rejected client
    # certificate included) and would build without pushing anything.
    states="$(bst_show artifact show --deps none "${ELEMENTS[@]}")"
    if grep -qF "Failed to initialize remote ${PUSH_URL}" <<< "${states}"; then
        grep -F "Failed to initialize remote ${PUSH_URL}" <<< "${states}" >&2
        echo "kernel-cache: cannot reach ${PUSH_URL}; refusing to build without pushing" >&2
        exit 1
    fi
    available="$(grep -cE '^ *available ' <<< "${states}" || true)"
    if [ "${available}" -eq "${#ELEMENTS[@]}" ]; then
        echo "kernel-cache: ${variant}: ${ELEMENTS[*]} already on a remote"
        return 0
    fi
    just bst build "${ELEMENTS[@]}"
    echo "kernel-cache: ${variant}: pushed ${ELEMENTS[*]} to ${PUSH_URL}"
}

case "${1:-} ${2:-}" in
    "seed release" | "seed dev") seed "$2" ;;
    *) echo "usage: $0 seed release|dev" >&2; exit 2 ;;
esac
