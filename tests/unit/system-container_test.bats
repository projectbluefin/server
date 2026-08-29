#!/usr/bin/env bats
#
# Unit tests for files/bin/system-container.
#
# The script is a root-gated dispatcher around machinectl. It is executed in a
# sandbox with stub `id`, `sudo` and `machinectl` binaries prepended to PATH so
# no privilege escalation or container operation ever happens for real.

setup() {
    REPO_ROOT="$(cd "${BATS_TEST_DIRNAME}/../.." && pwd)"
    SCRIPT="${REPO_ROOT}/files/bin/system-container"
    STUB_DIR="${BATS_TEST_TMPDIR}/bin"
    LOG="${BATS_TEST_TMPDIR}/calls.log"
    mkdir -p "$STUB_DIR"
    : > "$LOG"

    # Default: pretend we are already root so the sudo re-exec branch is skipped.
    make_id_stub 0
    make_sudo_stub
    make_machinectl_stub 0
}

make_id_stub() {
    cat > "${STUB_DIR}/id" <<EOF
#!/usr/bin/env bash
if [ "\${1:-}" = "-u" ]; then
    echo "$1"
    exit 0
fi
exec /usr/bin/id "\$@"
EOF
    chmod +x "${STUB_DIR}/id"
}

make_sudo_stub() {
    cat > "${STUB_DIR}/sudo" <<EOF
#!/usr/bin/env bash
echo "sudo \$*" >> "${LOG}"
exit 0
EOF
    chmod +x "${STUB_DIR}/sudo"
}

# make_machinectl_stub <exit-code>
make_machinectl_stub() {
    cat > "${STUB_DIR}/machinectl" <<EOF
#!/usr/bin/env bash
echo "machinectl \$*" >> "${LOG}"
exit $1
EOF
    chmod +x "${STUB_DIR}/machinectl"
}

run_sc() {
    run env PATH="${STUB_DIR}:${PATH}" bash "$SCRIPT" "$@"
}

calls() {
    cat "$LOG"
}

# --- the script itself -------------------------------------------------------

@test "script exists and is executable" {
    [ -f "$SCRIPT" ]
    [ -x "$SCRIPT" ]
}

@test "script uses strict bash mode" {
    run grep -q '^set -euo pipefail$' "$SCRIPT"
    [ "$status" -eq 0 ]
}

# --- privilege gate ----------------------------------------------------------

@test "non-root invocation re-execs itself through sudo" {
    make_id_stub 1000
    run_sc start web
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"sudo ${SCRIPT} start web"* ]]
    # The real command must not have run in the unprivileged pass.
    [[ "$output" != *"machinectl"* ]]
}

@test "non-root re-exec forwards a bare invocation with no arguments" {
    make_id_stub 1000
    run_sc
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" == *"sudo ${SCRIPT}"* ]]
}

@test "root invocation does not call sudo" {
    run_sc start web
    [ "$status" -eq 0 ]
    run calls
    [[ "$output" != *"sudo"* ]]
}

# --- start -------------------------------------------------------------------

@test "start <name> calls machinectl start" {
    run_sc start web
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl start web" ]
}

@test "start without a name exits 1 with a usage message on stderr" {
    run_sc start
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container start <name>"* ]]
    [ ! -s "$LOG" ]
}

@test "start with an empty name argument exits 1" {
    run_sc start ""
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container start <name>"* ]]
    [ ! -s "$LOG" ]
}

@test "start propagates a machinectl failure" {
    make_machinectl_stub 7
    run_sc start web
    [ "$status" -eq 7 ]
}

# --- stop --------------------------------------------------------------------

@test "stop <name> calls machinectl poweroff, not machinectl stop" {
    run_sc stop web
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl poweroff web" ]
}

@test "stop without a name exits 1 with a usage message" {
    run_sc stop
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container stop <name>"* ]]
    [ ! -s "$LOG" ]
}

@test "stop propagates a machinectl failure" {
    make_machinectl_stub 3
    run_sc stop web
    [ "$status" -eq 3 ]
}

# --- enter -------------------------------------------------------------------

@test "enter <name> calls machinectl shell" {
    run_sc enter web
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl shell web" ]
}

@test "enter without a name exits 1 with a usage message" {
    run_sc enter
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container enter <name>"* ]]
    [ ! -s "$LOG" ]
}

# --- reset -------------------------------------------------------------------

@test "reset <name> calls machinectl remove" {
    run_sc reset web
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl remove web" ]
}

@test "reset without a name exits 1 and removes nothing" {
    run_sc reset
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container reset <name>"* ]]
    [ ! -s "$LOG" ]
}

@test "reset propagates a machinectl failure" {
    make_machinectl_stub 5
    run_sc reset web
    [ "$status" -eq 5 ]
}

# --- dispatch / usage --------------------------------------------------------

@test "no arguments falls through to the usage branch and exits 1" {
    run_sc
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container {start|stop|enter|reset} <name>"* ]]
    [ ! -s "$LOG" ]
}

@test "explicit help is not a real subcommand and exits 1" {
    run_sc help
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container {start|stop|enter|reset} <name>"* ]]
}

@test "unknown subcommand exits 1 without touching machinectl" {
    run_sc destroy web
    [ "$status" -eq 1 ]
    [[ "$output" == *"usage: system-container {start|stop|enter|reset} <name>"* ]]
    [ ! -s "$LOG" ]
}

@test "subcommand matching is case sensitive" {
    run_sc START web
    [ "$status" -eq 1 ]
    [ ! -s "$LOG" ]
}

@test "usage output goes to stderr, not stdout" {
    output="$(env PATH="${STUB_DIR}:${PATH}" bash "$SCRIPT" bogus 2>/dev/null || true)"
    [ -z "$output" ]
}

@test "machine names containing spaces are passed as a single argument" {
    run_sc start "my machine"
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl start my machine" ]
}

@test "extra trailing arguments are ignored" {
    run_sc start web extra1 extra2
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl start web" ]
}

@test "the script performs no option parsing — a leading -- is treated as the machine name" {
    run_sc start -- --all
    [ "$status" -eq 0 ]
    run calls
    [ "$output" = "machinectl start --" ]
}
