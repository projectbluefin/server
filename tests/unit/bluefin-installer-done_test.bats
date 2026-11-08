#!/usr/bin/env bats
#
# Unit tests for files/os/libexec/bluefin-installer-done: the USB installer's
# last screen once systemd-sysinstall succeeded (#311).

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/files/os/libexec/bluefin-installer-done"
    export BLUEFIN_OS_RELEASE="${BATS_TEST_TMPDIR}/os-release"
    printf 'ID=bluefin-server\nIMAGE_VERSION="26.10.1"\n' > "${BLUEFIN_OS_RELEASE}"
}

@test "says the install is done, when to remove the stick and what comes next" {
    BLUEFIN_INSTALLER_DONE_TIMEOUT=1 run bash "${SCRIPT}" < /dev/null
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Bluefin Server 26.10.1 is installed."* ]]
    [[ "${output}" == *"The machine restarts into it in 1 seconds (Enter: now)."* ]]
    [[ "${output}" == *"Remove the USB stick when the screen goes blank."* ]]
    [[ "${output}" == *"asks here for a new root"* ]]
    [[ "${output}" == *"log in as root with it."* ]]
    [[ "${output}" == *"Restarting."* ]]
}

@test "waits for the countdown when nobody presses Enter" {
    start=${SECONDS}
    # stdin stays open, with nothing to read, for longer than the countdown.
    BLUEFIN_INSTALLER_DONE_TIMEOUT=2 run bash -c 'sleep 5 | bash "$1"' _ "${SCRIPT}"
    [ "${status}" -eq 0 ]
    [ $(( SECONDS - start )) -ge 2 ]
}

@test "Enter restarts at once" {
    start=${SECONDS}
    BLUEFIN_INSTALLER_DONE_TIMEOUT=30 run bash "${SCRIPT}" <<< ""
    [ "${status}" -eq 0 ]
    [ $(( SECONDS - start )) -lt 10 ]
}

@test "the default countdown is 15 seconds" {
    run grep -F 'timeout="${BLUEFIN_INSTALLER_DONE_TIMEOUT:-15}"' "${SCRIPT}"
    [ "${status}" -eq 0 ]
}

@test "without an os-release it still says installed" {
    BLUEFIN_OS_RELEASE=/nonexistent BLUEFIN_INSTALLER_DONE_TIMEOUT=0 run bash "${SCRIPT}" < /dev/null
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Bluefin Server is installed."* ]]
}

@test "Home Server mentions Homebrew seeding" {
    export CREDENTIALS_DIRECTORY="${BATS_TEST_TMPDIR}/creds"
    mkdir -p "${CREDENTIALS_DIRECTORY}"
    printf 1 > "${CREDENTIALS_DIRECTORY}/bluefin.install-home-server"
    BLUEFIN_INSTALLER_DONE_TIMEOUT=0 run bash "${SCRIPT}" < /dev/null
    [ "${status}" -eq 0 ]
    [[ "${output}" == *"Bluefin Home Server is installed."* ]]
    [[ "${output}" == *"Homebrew is seeded"* ]]
}
