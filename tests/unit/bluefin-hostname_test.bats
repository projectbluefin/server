#!/usr/bin/env bats
#
# Unit tests for files/os/libexec/bluefin-hostname: a node without a static
# hostname gets a provisioned or a bluefin-<machine-id[:8]> one; a set name
# is kept; an invalid one fails without anything being written (#82).

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/files/os/libexec/bluefin-hostname"
    ROOT="${BATS_TEST_TMPDIR}/root"
    export CREDENTIALS_DIRECTORY="${BATS_TEST_TMPDIR}/creds"
    mkdir -p "${ROOT}/etc" "${CREDENTIALS_DIRECTORY}"
    printf '0123abcd456789ef0123456789abcdef\n' > "${ROOT}/etc/machine-id"
}

helper() { run bash "${SCRIPT}" --root="${ROOT}"; }
static() { cat "${ROOT}/etc/hostname"; }

@test "no static hostname: bluefin-<first 8 of the machine ID>" {
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "bluefin-0123abcd" ]
    [[ "${output}" == *"set hostname bluefin-0123abcd (from machine ID)"* ]]
}

@test "localhost and its variants count as unset" {
    for name in localhost LOCALHOST localhost. localhost.localdomain node.localhost '# comment'; do
        printf '%s\n' "${name}" > "${ROOT}/etc/hostname"
        helper
        [ "${status}" -eq 0 ]
        [ "$(static)" = "bluefin-0123abcd" ]
    done
}

@test "an empty /etc/hostname counts as unset" {
    : > "${ROOT}/etc/hostname"
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "bluefin-0123abcd" ]
}

@test "a static hostname is kept (Ignition, firstboot.hostname, hostnamectl)" {
    printf '# set by hostnamectl\n  blueserver-1  \n' > "${ROOT}/etc/hostname"
    printf 'other\n' > "${CREDENTIALS_DIRECTORY}/system.hostname"
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "$(printf '# set by hostnamectl\n  blueserver-1  ')" ]
    [[ "${output}" == *"keeping static hostname blueserver-1"* ]]
}

@test "an invalid static hostname fails and is not replaced" {
    printf 'bad_name\n' > "${ROOT}/etc/hostname"
    helper
    [ "${status}" -eq 1 ]
    [ "$(static)" = "bad_name" ]
    [[ "${output}" == *"invalid static hostname in /etc/hostname: bad_name"* ]]
}

@test "firstboot.hostname wins over system.hostname and the machine ID" {
    printf 'blueserver-0\n' > "${CREDENTIALS_DIRECTORY}/firstboot.hostname"
    printf 'transient\n' > "${CREDENTIALS_DIRECTORY}/system.hostname"
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "blueserver-0" ]
    [[ "${output}" == *"(from credential firstboot.hostname)"* ]]
}

@test "system.hostname becomes the static hostname" {
    printf 'rack1-node4.example.com' > "${CREDENTIALS_DIRECTORY}/system.hostname"
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "rack1-node4.example.com" ]
}

@test "an invalid hostname credential fails; nothing is written, no fallback" {
    for value in 'bad name' '-lead' 'trail-' 'a..b' 'under_score' "$(printf 'x%.0s' {1..64})" "$(printf 'a%.0s' {1..60}).example"; do
        rm -f "${ROOT}/etc/hostname"
        printf '%s' "${value}" > "${CREDENTIALS_DIRECTORY}/system.hostname"
        helper
        [ "${status}" -eq 1 ]
        [ ! -e "${ROOT}/etc/hostname" ]
        [[ "${output}" == *"invalid hostname in credential system.hostname"* ]]
    done
}

@test "an invalid firstboot.hostname is not replaced by system.hostname" {
    printf 'bad_name' > "${CREDENTIALS_DIRECTORY}/firstboot.hostname"
    printf 'good' > "${CREDENTIALS_DIRECTORY}/system.hostname"
    helper
    [ "${status}" -eq 1 ]
    [ ! -e "${ROOT}/etc/hostname" ]
}

@test "the longest valid label and name are accepted" {
    label="$(printf 'a%.0s' {1..63})"
    printf '%s' "${label}" > "${CREDENTIALS_DIRECTORY}/system.hostname"
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "${label}" ]
}

@test "no machine ID and no credential: fails, nothing written" {
    for id in '' uninitialized 0123; do
        printf '%s\n' "${id}" > "${ROOT}/etc/machine-id"
        helper
        [ "${status}" -eq 1 ]
        [ ! -e "${ROOT}/etc/hostname" ]
        [[ "${output}" == *"no machine ID"* ]]
    done
}

@test "without a credentials directory it still names the node" {
    unset CREDENTIALS_DIRECTORY
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "bluefin-0123abcd" ]
}

@test "a second run keeps the name it gave" {
    helper
    printf 'fedcba98765432100123456789abcdef\n' > "${ROOT}/etc/machine-id"
    helper
    [ "${status}" -eq 0 ]
    [ "$(static)" = "bluefin-0123abcd" ]
}

@test "unknown arguments are refused" {
    run bash "${SCRIPT}" --bogus
    [ "${status}" -eq 2 ]
}
