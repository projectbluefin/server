#!/usr/bin/env bats
#
# Unit tests for the `k8s` recipe in files/os/justfile.
#
# The recipe interacts with /var/lib/extensions and enables host units, so every
# invocation runs inside an unprivileged user + mount namespace with tmpfs
# masks over /etc and /var/lib. Nothing on the host is touched. systemctl,
# systemd-sysext and systemd-sysupdate are replaced by logging stubs on PATH,
# so no unit is ever enabled and no OTA is ever fetched.
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

    # Defaults: every helper succeeds, and the sysext is not yet installed.
    make_stub systemctl 0
    make_stub systemd-sysext 0
    make_stub systemd-sysupdate 0
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
[ "$SYSEXT_PRESENT" = "1" ] && : > /var/lib/extensions/kubernetes.raw

just --justfile "$JUSTFILE" --working-directory "$WORKDIR" k8s "$@"
rc=$?
exit "$rc"
SANDBOX
}

calls() {
    cat "$LOG"
}

# --- the recipe file itself --------------------------------------------------

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

@test "a missing kubernetes.raw triggers a component-scoped systemd-sysupdate" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-sysupdate --component=kubernetes update"* ]]
}

@test "an existing kubernetes.raw skips systemd-sysupdate" {
    SYSEXT_PRESENT=1
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" != *"systemd-sysupdate"* ]]
}

@test "a failing systemd-sysupdate does not abort the recipe" {
    make_stub systemd-sysupdate 1
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemd-sysupdate --component=kubernetes update"* ]]
    [[ "$output" == *"systemctl enable --now bluefin-cluster-bootstrap.service"* ]]
}

# --- sysext merge & daemon-reload --------------------------------------------

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
    [[ "$output" == *"systemctl enable --now bluefin-cluster-bootstrap.service"* ]]
}

# A merge makes unit files appear under /usr but does not make systemd notice
# them. Without the reload, enabling bluefin-cluster-bootstrap.service fails on
# a host that has never merged the sysext before.
@test "systemd is reloaded after the merge and before the cluster units start" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl daemon-reload"* ]]
    reload_line="$(grep -n 'systemctl daemon-reload' "$LOG" | head -1 | cut -d: -f1)"
    bootstrap_line="$(grep -n 'bluefin-cluster-bootstrap.service' "$LOG" | head -1 | cut -d: -f1)"
    [ "$reload_line" -lt "$bootstrap_line" ]
}

# --- cluster bring-up --------------------------------------------------------

# bluefin-cluster-bootstrap.service carries Requires=/After= on
# kubeadm-init.service and bluefin-cluster-repo.service, so the recipe starts
# exactly one unit and systemd orders the rest.
@test "the default role enables bluefin-cluster-bootstrap.service" {
    run_k8s
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now bluefin-cluster-bootstrap.service"* ]]
}

@test "the controller role enables bluefin-cluster-bootstrap.service" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now bluefin-cluster-bootstrap.service"* ]]
}

@test "the server alias role enables bluefin-cluster-bootstrap.service" {
    run_k8s server
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"systemctl enable --now bluefin-cluster-bootstrap.service"* ]]
}

@test "the recipe does not start kubeadm-init or the repo unit directly" {
    run_k8s controller
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" != *"kubeadm-init.service"* ]]
    [[ "$output" != *"bluefin-cluster-repo.service"* ]]
}

# --- role dispatch -----------------------------------------------------------

@test "an unknown role exits 1 and names the supported roles" {
    run_k8s worker
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid role 'worker'"* ]]
    [[ "$output" == *"Supported: controller"* ]]
}

@test "an unknown role touches nothing on the host" {
    run_k8s worker
    [ "$status" -eq 1 ]
    run calls
    [[ "$output" != *"bluefin-cluster-bootstrap.service"* ]]
    [[ "$output" != *"systemd-sysupdate"* ]]
    [[ "$output" != *"systemd-sysext"* ]]
}

@test "the role comparison is case sensitive" {
    run_k8s Controller
    [ "$status" -eq 1 ]
    [[ "$output" == *"Invalid role 'Controller'"* ]]
}

# --- failure propagation -----------------------------------------------------

@test "a failing systemctl enable of the bootstrap unit fails the recipe" {
    make_stub systemctl 1
    run_k8s controller
    [ "$status" -ne 0 ]
    [[ "$output" != *"successfully configured"* ]]
}

@test "a successful run reports completion" {
    run_k8s controller
    [ "$status" -eq 0 ]
    [[ "$output" == *"Kubernetes has been successfully configured and started!"* ]]
}
