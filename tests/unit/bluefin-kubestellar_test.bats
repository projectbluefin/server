#!/usr/bin/env bats
# Behavioral tests for files/bin/bluefin-kubestellar single-command launcher.
#
# Every test runs hermetically: XDG_STATE_HOME points at a per-test temp dir and
# curl/kc-agent/brew resolve from a stub bin directory prepended to PATH, so no
# test touches the real host state dir, the network, or Homebrew.

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/files/bin/bluefin-kubestellar"

  export XDG_STATE_HOME="$BATS_TEST_TMPDIR/state"
  STATE_DIR="$XDG_STATE_HOME/bluefin-server"
  PID_FILE="$STATE_DIR/kc-agent.pid"
  LOG_FILE="$STATE_DIR/kc-agent.log"

  STUB_BIN="$BATS_TEST_TMPDIR/bin"
  STUB_LOG="$BATS_TEST_TMPDIR/stub.log"
  mkdir -p "$STUB_BIN"
  export PATH="$STUB_BIN:$PATH"
  export STUB_LOG

  # Default: the health endpoint always fails, so nothing is assumed running.
  stub_curl_unhealthy
}

# Writes a stub that records its argv to $STUB_LOG and exits with $2.
make_stub() {
  local name="$1" exit_code="$2"
  cat > "$STUB_BIN/$name" <<EOF
#!/usr/bin/env bash
echo "$name \$*" >> "\$STUB_LOG"
exit $exit_code
EOF
  chmod +x "$STUB_BIN/$name"
}

stub_curl_healthy() { make_stub curl 0; }
stub_curl_unhealthy() { make_stub curl 7; }

# curl that fails the pre-flight probe once, then reports healthy — the shape a
# real background start sees.
stub_curl_healthy_after_first_probe() {
  cat > "$STUB_BIN/curl" <<'EOF'
#!/usr/bin/env bash
echo "curl $*" >> "$STUB_LOG"
marker="$(dirname "$0")/.probed"
if [ -e "$marker" ]; then exit 0; fi
touch "$marker"
exit 7
EOF
  chmod +x "$STUB_BIN/curl"
}

# kc-agent that stays alive until killed, so PID bookkeeping is observable.
stub_kc_agent_running() {
  cat > "$STUB_BIN/kc-agent" <<'EOF'
#!/usr/bin/env bash
echo "kc-agent $*" >> "$STUB_LOG"
exec sleep 30
EOF
  chmod +x "$STUB_BIN/kc-agent"
}

# kc-agent that exits successfully at once — for foreground runs, which exec it.
stub_kc_agent_foreground() {
  make_stub kc-agent 0
}

# kc-agent that dies immediately with diagnostics on stdout.
stub_kc_agent_crashing() {
  cat > "$STUB_BIN/kc-agent" <<'EOF'
#!/usr/bin/env bash
echo "kc-agent $*" >> "$STUB_LOG"
echo "fatal: bind: address already in use"
exit 9
EOF
  chmod +x "$STUB_BIN/kc-agent"
}

# Runs the script with a PATH holding only the stub dir plus coreutils, so a
# real kc-agent or brew on the runner cannot leak into the test.
run_isolated() {
  run env PATH="$STUB_BIN:/usr/bin:/bin" "$SCRIPT" "$@"
}

# ── packaging ────────────────────────────────────────────────────────────────

@test "bluefin-kubestellar exists and is executable" {
  [ -f "$SCRIPT" ]
  [ -x "$SCRIPT" ]
}

# ── argument parsing ─────────────────────────────────────────────────────────

@test "help displays usage options" {
  run "$SCRIPT" help
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Usage:" ]]
  [[ "$output" =~ "--origin" ]]
  [[ "$output" =~ "--foreground" ]]
}

@test "-h and --help print usage without starting kc-agent" {
  for flag in -h --help; do
    run "$SCRIPT" "$flag"
    [ "$status" -eq 0 ]
    [[ "$output" =~ "Usage:" ]]
  done
  [ ! -f "$PID_FILE" ]
}

@test "rejects unknown command" {
  run "$SCRIPT" invalid-cmd
  [ "$status" -ne 0 ]
  [[ "$output" =~ "Unknown option or command" ]]
}

@test "unknown option prints usage to stderr" {
  run "$SCRIPT" --bogus
  [ "$status" -eq 1 ]
  [[ "$output" =~ "Unknown option or command: --bogus" ]]
  [[ "$output" =~ "Usage:" ]]
}

@test "--origin without a value is rejected" {
  run "$SCRIPT" --origin
  [ "$status" -eq 1 ]
  [[ "$output" =~ "--origin requires an argument" ]]
}

@test "--port without a value is rejected" {
  run "$SCRIPT" --port
  [ "$status" -eq 1 ]
  [[ "$output" =~ "--port requires an argument" ]]
}

@test "a bare http(s) URL is accepted as the origin" {
  stub_kc_agent_foreground
  run_isolated --foreground https://console.example.test:8080
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Allowed origins: https://console.example.test:8080" ]]
}

@test "--origin=<urls> and -o <urls> select the same origin" {
  stub_kc_agent_foreground
  run_isolated --foreground --origin=http://a.test:8080,http://b.test:8080
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Allowed origins: http://a.test:8080,http://b.test:8080" ]]

  run_isolated --foreground -o http://a.test:8080,http://b.test:8080
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Allowed origins: http://a.test:8080,http://b.test:8080" ]]
}

@test "a command word after options still selects the command" {
  run "$SCRIPT" --port 9000 help
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Usage:" ]]
}

# ── start ────────────────────────────────────────────────────────────────────

@test "start defaults to the localhost console origins" {
  stub_kc_agent_foreground
  run_isolated --foreground
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Allowed origins: http://localhost:8080,http://127.0.0.1:8080" ]]
}

@test "foreground start execs kc-agent with -allowed-origins" {
  stub_kc_agent_foreground
  run_isolated -f --origin http://console.test:8080
  [ "$status" -eq 0 ]
  grep -q -- "kc-agent -allowed-origins http://console.test:8080" "$STUB_LOG"
}

@test "foreground start disables in-cluster Kagenti DNS by default" {
  stub_kc_agent_foreground
  run_isolated --foreground
  [ "$status" -eq 0 ]
  [[ "$output" =~ "KAGENTI_CONTROLLER_URL: none" ]]
}

@test "an inherited KAGENTI_CONTROLLER_URL is preserved" {
  stub_kc_agent_foreground
  run env PATH="$STUB_BIN:/usr/bin:/bin" KAGENTI_CONTROLLER_URL=http://kagenti.test \
    "$SCRIPT" --foreground
  [ "$status" -eq 0 ]
  [[ "$output" =~ "KAGENTI_CONTROLLER_URL: http://kagenti.test" ]]
}

@test "start is a no-op when the agent is already healthy" {
  stub_curl_healthy
  stub_kc_agent_running
  run_isolated
  [ "$status" -eq 0 ]
  [[ "$output" =~ "already running and healthy" ]]
  # The early exit must not spawn kc-agent.
  ! grep -q "^kc-agent " "$STUB_LOG"
}

@test "foreground start ignores the already-healthy short circuit" {
  stub_curl_healthy
  stub_kc_agent_foreground
  run_isolated --foreground
  [ "$status" -eq 0 ]
  grep -q "^kc-agent " "$STUB_LOG"
}

@test "the start health probe defaults to port 8585 and honours --port" {
  stub_curl_healthy
  run_isolated --port 9999
  [ "$status" -eq 0 ]
  [[ "$output" =~ "http://127.0.0.1:9999/health" ]]

  run_isolated
  [ "$status" -eq 0 ]
  [[ "$output" =~ "http://127.0.0.1:8585/health" ]]
}

@test "--no-install fails closed when kc-agent is missing" {
  run_isolated --no-install
  [ "$status" -eq 1 ]
  [[ "$output" =~ "kc-agent is not installed and cannot be auto-installed" ]]
  [[ "$output" =~ "brew tap kubestellar/tap" ]]
}

@test "missing kc-agent is installed from kubestellar/tap via Homebrew" {
  # brew install must materialize kc-agent for the run to proceed.
  cat > "$STUB_BIN/brew" <<'EOF'
#!/usr/bin/env bash
echo "brew $*" >> "$STUB_LOG"
if [ "$1" = "install" ]; then
  cat > "$(dirname "$0")/kc-agent" <<'AGENT'
#!/usr/bin/env bash
echo "kc-agent $*" >> "$STUB_LOG"
AGENT
  chmod +x "$(dirname "$0")/kc-agent"
fi
EOF
  chmod +x "$STUB_BIN/brew"

  run_isolated --foreground
  [ "$status" -eq 0 ]
  grep -q "brew tap kubestellar/tap" "$STUB_LOG"
  grep -q "brew install kc-agent" "$STUB_LOG"
  grep -q "^kc-agent " "$STUB_LOG"
}

@test "background start records the PID and reports healthy" {
  stub_kc_agent_running
  stub_curl_healthy_after_first_probe

  run_isolated
  [ "$status" -eq 0 ]
  [[ "$output" =~ "kc-agent is healthy and connected" ]]
  [ -f "$PID_FILE" ]
  kill -0 "$(cat "$PID_FILE")"
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
}

@test "background start writes kc-agent output to the log file" {
  stub_kc_agent_running
  stub_curl_healthy_after_first_probe

  run_isolated
  [ "$status" -eq 0 ]
  [ -f "$LOG_FILE" ]
  [[ "$output" =~ "Log file: $LOG_FILE" ]]
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
}

@test "a kc-agent that exits immediately fails the start and clears the PID file" {
  stub_kc_agent_crashing
  run_isolated
  [ "$status" -eq 1 ]
  [[ "$output" =~ "exited unexpectedly" ]]
  [[ "$output" =~ "address already in use" ]]
  [ ! -f "$PID_FILE" ]
}

@test "background start replaces a live PID from a previous run" {
  stub_kc_agent_running
  stub_curl_healthy_after_first_probe
  mkdir -p "$STATE_DIR"
  sleep 30 &
  OLD_PID=$!
  echo "$OLD_PID" > "$PID_FILE"

  run_isolated
  [ "$status" -eq 0 ]
  NEW_PID="$(cat "$PID_FILE")"
  [ "$NEW_PID" != "$OLD_PID" ]
  kill "$NEW_PID" 2>/dev/null || true
  # Final command: its status gates the test, so a surviving old process fails.
  ! kill -0 "$OLD_PID" 2>/dev/null
}

# ── stop ─────────────────────────────────────────────────────────────────────

@test "stop reports when no PID file exists" {
  run "$SCRIPT" stop
  [ "$status" -eq 0 ]
  [[ "$output" =~ "No active kc-agent PID file found" ]]
}

@test "stop terminates a live agent and removes the PID file" {
  mkdir -p "$STATE_DIR"
  sleep 30 &
  PID=$!
  echo "$PID" > "$PID_FILE"

  run "$SCRIPT" stop
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Stopped kc-agent (PID: $PID)" ]]
  [ ! -f "$PID_FILE" ]
  ! kill -0 "$PID" 2>/dev/null
}

@test "stop clears a stale PID file without an error" {
  mkdir -p "$STATE_DIR"
  sleep 30 &
  PID=$!
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  echo "$PID" > "$PID_FILE"

  run "$SCRIPT" stop
  [ "$status" -eq 0 ]
  [[ "$output" =~ "was not running" ]]
  [ ! -f "$PID_FILE" ]
}

# ── status ───────────────────────────────────────────────────────────────────

@test "status exits 3 when nothing is running" {
  run "$SCRIPT" status
  [ "$status" -eq 3 ]
  [[ "$output" =~ "kc-agent is not running" ]]
}

@test "status exits 0 and reports the PID when the health probe succeeds" {
  stub_curl_healthy
  mkdir -p "$STATE_DIR"
  echo 4242 > "$PID_FILE"

  run "$SCRIPT" status
  [ "$status" -eq 0 ]
  [[ "$output" =~ "running and healthy" ]]
  [[ "$output" =~ "Process PID: 4242" ]]
}

@test "status probes the health endpoint on --port" {
  stub_curl_healthy
  run "$SCRIPT" status --port 9100
  [ "$status" -eq 0 ]
  [[ "$output" =~ "http://127.0.0.1:9100/health" ]]
}

@test "status exits 1 when the process is alive but unhealthy" {
  mkdir -p "$STATE_DIR"
  sleep 30 &
  PID=$!
  echo "$PID" > "$PID_FILE"

  run "$SCRIPT" status
  [ "$status" -eq 1 ]
  [[ "$output" =~ "is running but" ]]
  [[ "$output" =~ "not responding" ]]
  kill "$PID" 2>/dev/null || true
}

@test "status exits 3 for a stale PID file with no live process" {
  mkdir -p "$STATE_DIR"
  sleep 30 &
  PID=$!
  kill "$PID" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
  echo "$PID" > "$PID_FILE"

  run "$SCRIPT" status
  [ "$status" -eq 3 ]
  [[ "$output" =~ "kc-agent is not running" ]]
}

# ── logs ─────────────────────────────────────────────────────────────────────

@test "logs reports the missing log file path" {
  run "$SCRIPT" logs
  [ "$status" -eq 0 ]
  [[ "$output" =~ "No log file found at" ]]
  [[ "$output" =~ "kc-agent.log" ]]
}

@test "logs prints the tail of the log file" {
  mkdir -p "$STATE_DIR"
  for i in $(seq 1 60); do echo "line $i" >> "$LOG_FILE"; done

  run "$SCRIPT" logs
  [ "$status" -eq 0 ]
  [[ "$output" =~ "line 60" ]]
  [[ "$output" =~ "line 11" ]]
  # Only the last 50 lines are shown.
  [[ ! "$output" =~ "line 10" ]]
}
