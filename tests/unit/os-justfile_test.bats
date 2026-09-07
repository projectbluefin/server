#!/usr/bin/env bats
#
# Unit tests for the `k8s` recipe in files/os/justfile.
#
# The recipe interacts with /etc/k0s and /var/lib/extensions, so every
# invocation runs inside an unprivileged user + mount namespace with tmpfs
# masks over /etc and /var/lib. Nothing on the host is touched. systemctl,
# systemd-sysext, systemd-sysupdate, and systemd-tmpfiles are replaced by
# logging stubs on PATH, so no unit is ever enabled and no OTA is ever fetched.
#
# Results that must outlive the namespace (the call log) are copied back
# into BATS_TEST_TMPDIR, which is outside both tmpfs masks.

setup() {
    if ! unshare --map-root-user --mount true 2>/dev/null; then
        skip "unprivileged user+mount namespaces are unavailable"
    fi
    if ! command -v just >/dev/null 2>&1; then
        skip "just is not installed"
    fi

    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    JUSTFILE="${REPO_ROOT}/files/os/justfile"
    STUB_DIR="${BATS_TEST_TMPDIR}/bin"
    LOG="${BATS_TEST_TMPDIR}/calls.log"

    mkdir -p "$STUB_DIR"
    : > "$LOG"

    # The recipe cannot be exercised at all while the justfile is unparseable.
    # The behavioural tests skip in that state so the suite reports exactly one
    # failure -- the parse gate below -- instead of twenty derived ones.
    if just --justfile "$JUSTFILE" --summary >/dev/null 2>&1; then
        JUSTFILE_PARSES=1
    else
        JUSTFILE_PARSES=0
    fi

    # Defaults: every helper succeeds, and the k0s sysext is not yet present.
    make_stub systemctl 0
    make_stub systemd-sysext 0
    make_stub systemd-sysupdate 0
    make_stub systemd-tmpfiles 0
    SYSEXT_PRESENT=0
}

# make_stub <name> <exit-code>
make_stub() {
    cat > "${STUB_DIR}/$1" <<EOF
#!/usr/bin/env bash
echo "$1 \$*" >> "${LOG}"
exit $2
EOF
    chmod +x "${STUB_DIR}/$1"
}

# run_k8s [args...] -- invoke `just k8s` inside the namespace sandbox.
run_k8s() {
    [ "$JUSTFILE_PARSES" = "1" ] || \
        skip "files/os/justfile does not parse; see the parse gate test"
    run env \
        PATH="${STUB_DIR}:${PATH}" \
        LOG="$LOG" \
        JUSTFILE="$JUSTFILE" \
        SYSEXT_PRESENT="$SYSEXT_PRESENT" \
        WORKDIR="$BATS_TEST_TMPDIR" \
        unshare --map-root-user --mount bash -s "$@" <<'SANDBOX'
set -u
mount -t tmpfs tmpfs /etc
mount -t tmpfs tmpfs /var/lib
mkdir -p /var/lib/extensions
[ "$SYSEXT_PRESENT" = "1" ] && : > /var/lib/extensions/k0s.raw

just --justfile "$JUSTFILE" --working-directory "$WORKDIR" k8s "$@"
rc=$?
exit "$rc"
SANDBOX
}

calls() {
    cat "$LOG"
}

# --- the recipe file itself --------------------------------------------------

# This is the parse gate. It fails on the current tree: the `cat <<EOF` body
# inside the k8s recipe sits at column 0, which resets just's recipe
# indentation and makes the closing `fi` an inconsistent-whitespace error.
# Reproduced on just 1.14.0, 1.25.2, 1.36.0, 1.40.0 and 1.42.4, so `just k8s`
# has never been runnable on a shipped image.
@test "the justfile parses and exposes k8s" {
    run just --justfile "$JUSTFILE" --summary
    [ "$status" -eq 0 ]
    [[ "$output" == *"k8s"* ]]
}

@test "the k8s recipe body runs under strict bash mode" {
    run grep -q '^    set -euo pipefail$' "$JUSTFILE"
    [ "$status" -eq 0 ]
}

# --- sysext acquisition ------------------------------------------------------

@test "a missing k0s.raw triggers systemd-sysupdate" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-sysupdate update"* ]]
}

@test "an existing k0s.raw skips systemd-sysupdate" {
    SYSEXT_PRESENT=1
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" != *"systemd-sysupdate update"* ]]
}

@test "a failing systemd-sysupdate does not abort the recipe" {
    make_stub systemd-sysupdate 1
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-sysupdate update"* ]]
    [[ "$output" == *"systemctl enable --now k0scontroller.service"* ]]
}

# --- sysext merge & tmpfiles -------------------------------------------------

@test "the sysext service is enabled and the extensions are merged" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now systemd-sysext.service"* ]]
    [[ "$output" == *"systemd-sysext merge"* ]]
}

@test "a failing sysext merge does not abort the recipe" {
    make_stub systemd-sysext 1
    make_stub systemctl 0
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k0scontroller.service"* ]]
}

@test "tmpfiles are seeded for k0s manifests" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-tmpfiles --create /usr/lib/tmpfiles.d/k0s-manifests.conf"* ]]
}

# --- role dispatch -----------------------------------------------------------

@test "the default role enables k0scontroller.service" {
    run_k8s
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k0scontroller.service"* ]]
}

@test "the controller role enables k0scontroller.service" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k0scontroller.service"* ]]
}

@test "the server alias role enables k0scontroller.service" {
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k0scontroller.service"* ]]
}

@test "an unknown role exits 1 and names the supported roles" {
    run_k8s worker
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid role 'worker'"* ]]
    [[ "$output" == *"Supported: controller"* ]]
}

@test "an unknown role enables no k0s unit" {
    run_k8s worker
    [ "$status" -eq 1 ]
    run calls
    [[ "$output" != *"k0scontroller.service"* ]]
}

@test "the role comparison is case sensitive" {
    run_k8s Controller
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid role 'Controller'"* ]]
}

# --- failure propagation -----------------------------------------------------

@test "a failing systemctl enable of k0scontroller.service fails the recipe" {
    make_stub systemctl 1
    run_k8s controller
    [ "$status" -ne 0 ]
    [[ "$output" != *"successfully configured"* ]]
}

@test "a successful run reports completion" {
    run_k8s controller
    [ "$status" -eq 0 ]
    [[ "$output" == *"k0s Kubernetes has been successfully configured and started!"* ]]
}
