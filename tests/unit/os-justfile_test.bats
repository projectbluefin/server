#!/usr/bin/env bats
#
# Unit tests for the `k8s` recipe in files/os/justfile.
#
# The recipe writes to absolute host paths (/etc/rancher/k3s) and probes
# /var/lib/extensions, so every invocation runs inside an unprivileged user +
# mount namespace with tmpfs masks over /etc and /var/lib. Nothing on the host
# is touched. systemctl, systemd-sysext and systemd-sysupdate are replaced by
# logging stubs on PATH, so no unit is ever enabled and no OTA is ever fetched.
#
# Results that must outlive the namespace (the call log, the seeded config) are
# copied back into BATS_TEST_TMPDIR, which is outside both tmpfs masks.

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
    OUT_CONFIG="${BATS_TEST_TMPDIR}/config.yaml"

    mkdir -p "$STUB_DIR"
    : > "$LOG"
    rm -f "$OUT_CONFIG"

    # The recipe cannot be exercised at all while the justfile is unparseable.
    # The behavioural tests skip in that state so the suite reports exactly one
    # failure -- the parse gate below -- instead of twenty derived ones.
    if just --justfile "$JUSTFILE" --summary >/dev/null 2>&1; then
        JUSTFILE_PARSES=1
    else
        JUSTFILE_PARSES=0
    fi

    # Defaults: every helper succeeds, and the k3s sysext is not yet present.
    make_stub systemctl 0
    make_stub systemd-sysext 0
    make_stub systemd-sysupdate 0
    SYSEXT_PRESENT=0
    SEED_CONFIG=""
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
        OUT_CONFIG="$OUT_CONFIG" \
        SYSEXT_PRESENT="$SYSEXT_PRESENT" \
        SEED_CONFIG="$SEED_CONFIG" \
        WORKDIR="$BATS_TEST_TMPDIR" \
        unshare --map-root-user --mount bash -s "$@" <<'SANDBOX'
set -u
mount -t tmpfs tmpfs /etc
mount -t tmpfs tmpfs /var/lib
mkdir -p /var/lib/extensions
[ "$SYSEXT_PRESENT" = "1" ] && : > /var/lib/extensions/k3s.raw
if [ -n "$SEED_CONFIG" ]; then
    mkdir -p /etc/rancher/k3s
    printf '%s' "$SEED_CONFIG" > /etc/rancher/k3s/config.yaml
fi

just --justfile "$JUSTFILE" --working-directory "$WORKDIR" k8s "$@"
rc=$?

[ -f /etc/rancher/k3s/config.yaml ] && cp /etc/rancher/k3s/config.yaml "$OUT_CONFIG"
exit "$rc"
SANDBOX
}

calls() {
    cat "$LOG"
}

config() {
    cat "$OUT_CONFIG"
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

@test "a missing k3s.raw triggers systemd-sysupdate" {
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-sysupdate update"* ]]
}

@test "an existing k3s.raw skips systemd-sysupdate" {
    SYSEXT_PRESENT=1
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" != *"systemd-sysupdate update"* ]]
}

@test "a failing systemd-sysupdate does not abort the recipe" {
    make_stub systemd-sysupdate 1
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-sysupdate update"* ]]
    [[ "$output" == *"systemctl enable --now k3s.service"* ]]
}

# --- config seeding ----------------------------------------------------------

@test "a fresh host gets a seeded /etc/rancher/k3s/config.yaml" {
    run_k8s server
    [ "$status" -eq 0 ]
    [ -f "$OUT_CONFIG" ]
    run config
    [[ "$output" == *"write-kubeconfig-mode:"* ]]
}

@test "no token argument seeds a config without a token line" {
    run_k8s server
    [ "$status" -eq 0 ]
    run config
    [[ "$output" != *"token:"* ]]
}

@test "a token argument is written as a quoted token line" {
    run_k8s server "s3cr3t"
    [ "$status" -eq 0 ]
    run config
    [[ "$output" == *'token: "s3cr3t"'* ]]
}

@test "an empty token argument is treated as no token" {
    run_k8s server ""
    [ "$status" -eq 0 ]
    run config
    [[ "$output" != *"token:"* ]]
}

@test "an existing config.yaml is never overwritten" {
    SEED_CONFIG=$'# operator owned\nwrite-kubeconfig-mode: "0600"\n'
    run_k8s server "s3cr3t"
    [ "$status" -eq 0 ]
    run config
    [[ "$output" == *"# operator owned"* ]]
    [[ "$output" != *"token:"* ]]
}

# --- sysext merge ------------------------------------------------------------

@test "the sysext service is enabled and the extensions are merged" {
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now systemd-sysext.service"* ]]
    [[ "$output" == *"systemd-sysext merge"* ]]
}

@test "a failing sysext merge does not abort the recipe" {
    make_stub systemd-sysext 1
    make_stub systemctl 0
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k3s.service"* ]]
}

# --- role dispatch -----------------------------------------------------------

@test "the server role enables k3s.service" {
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k3s.service"* ]]
    [[ "$output" != *"k3s-agent.service"* ]]
}

@test "the agent role enables k3s-agent.service" {
    run_k8s agent
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k3s-agent.service"* ]]
}

@test "the default role is server" {
    run_k8s
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now k3s.service"* ]]
    [[ "$output" != *"k3s-agent.service"* ]]
}

@test "an unknown role exits 1 and names the supported roles" {
    run_k8s worker
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid role 'worker'"* ]]
    [[ "$output" == *"Supported: server, agent"* ]]
}

@test "an unknown role enables no k3s unit" {
    run_k8s worker
    [ "$status" -eq 1 ]
    run calls
    [[ "$output" != *"k3s.service"* ]]
    [[ "$output" != *"k3s-agent.service"* ]]
}

@test "the role comparison is case sensitive" {
    run_k8s Server
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid role 'Server'"* ]]
}

# --- failure propagation -----------------------------------------------------

@test "a failing systemctl enable of k3s.service fails the recipe" {
    make_stub systemctl 1
    run_k8s server
    [ "$status" -ne 0 ]
    [[ "$output" != *"successfully configured"* ]]
}

@test "a successful run reports completion" {
    run_k8s server
    [ "$status" -eq 0 ]
    [[ "$output" == *"successfully configured"* ]]
}
