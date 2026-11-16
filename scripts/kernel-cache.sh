#!/usr/bin/env bash
# Key-free BuildStream cache of hot SDK, Brew and unsigned kernel/module outputs.
#
#   CASD_CLIENT_CERT=<pem> CASD_CLIENT_KEY=<pem> kernel-cache.sh seed shared|release|dev
#
# The kernel is most of a cold build (figures: docs/skills/ci-tooling.md,
# "Build time and caches") and no upstream cache holds it: its cache key
# depends on the module certificate it trusts (the
# linux-module-cert junction override) and on the patches in
# patches/freedesktop-sdk/ that edit its config (0006 kubenet, 0007 watchdog,
# 0009 no-firmware drivers and zstd).
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
# `seed shared` warms certificate-independent tools once. Release/dev then
# warm their kernel and modules. Ordinary builds reuse cached compiler parents
# instead of reconstructing every bootstrap ancestor. Each seed explicitly
# pushes its selected outputs with an mTLS-authenticated BuildStream config;
# newly built dependencies and sources also push normally. Every build reads
# them back through the anonymous remote that the FSDK patch adds to the junction's
# project.conf (the top-level project.conf remote does not reach junction
# elements such as the kernel). `available` only proves remote metadata exists;
# `bst build` must check selected payloads before `artifact push --deps none`.
#
# The CAS is publicly readable. What `seed` pushes is key-free by
# construction: the seed job holds no signing secrets, `seed` refuses to
# build if bluefin-server/keys/boot-keys.bst (the only element that stages
# private keys) is anywhere in its full graph. Shared outputs must not reach
# the module certificate either. Variant seeds refuse a files/boot-keys/modules/
# containing anything but the public certificate; that import may be pushed.
set -euo pipefail

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
    local variant="$1" graph states
    local -a elements
    : "${CASD_CLIENT_CERT:?kernel-cache: CASD_CLIENT_CERT is not set}"
    : "${CASD_CLIENT_KEY:?kernel-cache: CASD_CLIENT_KEY is not set}"
    if [ "${variant}" = shared ]; then
        elements=(
            freedesktop-sdk.bst:components/go.bst
            freedesktop-sdk.bst:bootstrap/build/gcc-stage2.bst
            freedesktop-sdk.bst:components/ruby.bst
            freedesktop-sdk.bst:components/_private/systemd-base.bst
        )
    else
        elements=(
            freedesktop-sdk.bst:components/linux.bst
            zfs/openzfs.bst
            nvidia/nvidia-open-595.bst
        )
        stage_cert "${variant}"
    fi
    # Read the whole graph before matching: `bst show | grep -q` under
    # pipefail turns a match into SIGPIPE when grep exits before bst finishes
    # writing, and a failed `bst show` would look like a graph without the keys.
    graph="$(bst_show show --deps all --format "'%{name}'" "${elements[@]}")" \
        || { echo "kernel-cache: cannot list the graph of ${elements[*]}; refusing to publish" >&2; exit 1; }
    if grep -qxF "${KEYS_ELEMENT}" <<< "${graph}"; then
        echo "kernel-cache: ${KEYS_ELEMENT} is in the graph of ${elements[*]}; refusing to publish" >&2
        exit 1
    fi
    if [ "${variant}" = shared ] && grep -qxF bluefin-server/keys/linux-module-cert.bst <<< "${graph}"; then
        echo "kernel-cache: shared outputs depend on the variant certificate; refusing to publish" >&2
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
    states="$(bst_show artifact show --deps none "${elements[@]}")"
    if grep -qF "Failed to initialize remote ${PUSH_URL}" <<< "${states}"; then
        grep -F "Failed to initialize remote ${PUSH_URL}" <<< "${states}" >&2
        echo "kernel-cache: cannot reach ${PUSH_URL}; refusing to build without pushing" >&2
        exit 1
    fi
    # Push cached upstream outputs too, without demanding missing bootstrap
    # ancestors.
    just bst build "${elements[@]}"
    just bst artifact push --deps none "${elements[@]}"
    echo "kernel-cache: ${variant}: pushed ${elements[*]} to ${PUSH_URL}"
}

case "${1:-} ${2:-}" in
    "seed shared" | "seed release" | "seed dev") seed "$2" ;;
    *) echo "usage: $0 seed shared|release|dev" >&2; exit 2 ;;
esac
