#!/usr/bin/env bats
# Tests for files/bin/bluefin-kubestellar single-command launcher

setup() {
  REPO_ROOT="$(cd "$BATS_TEST_DIRNAME/../.." && pwd)"
  SCRIPT="$REPO_ROOT/files/bin/bluefin-kubestellar"
}

@test "bluefin-kubestellar exists and is executable" {
  [ -f "$SCRIPT" ]
  [ -x "$SCRIPT" ]
}

@test "bluefin-kubestellar help displays usage options" {
  run "$SCRIPT" help
  [ "$status" -eq 0 ]
  [[ "$output" =~ "Usage:" ]]
  [[ "$output" =~ "--origin" ]]
  [[ "$output" =~ "--foreground" ]]
}

@test "bluefin-kubestellar rejects unknown command" {
  run "$SCRIPT" invalid-cmd
  [ "$status" -ne 0 ]
  [[ "$output" =~ "Unknown option or command" ]]
}

@test "bluefin-kubestellar status exits cleanly when agent is not running" {
  run "$SCRIPT" status
  # Exit code 3 signifies not running
  [ "$status" -eq 3 ] || [ "$status" -eq 0 ]
}
