"""Behavioural coverage for files/k0s/kiosk/kiosk-gate.js.

``kiosk-gate.js`` is the only thing standing between a kiosk visitor and a
console that looks logged-in but has no kc-agent behind it: it polls the
agent's health endpoint and, while a session exists but the agent is
unreachable, covers the page with a modal and swallows keystrokes aimed
outside it.

Until now the script had no executed coverage at all. tests/unit/
test_kubestellar_kiosk.py asserts that certain strings appear in the file
(``kc-has-session``, the health URL, ``aria-modal``, the keydown
registration), which is a packaging contract, not a behavioural one. Every
one of those assertions still passes if the session check is inverted, if the
gate is shown when the agent is *healthy*, if a failed poll stacks a second
modal on every tick, or if the keydown trap fires when no gate is present.

These tests run the real script in node against a stub DOM
(``kiosk_gate_harness.mjs``) and assert what it actually does. Without node
they skip locally and fail in CI (the ``node`` fixture in conftest.py).
"""

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "files" / "k0s" / "kiosk" / "kiosk-gate.js"
HARNESS = Path(__file__).with_name("kiosk_gate_harness.mjs")


def run_gate(node: str, **scenario) -> dict:
    """Execute kiosk-gate.js under the stub DOM and return its observed effects."""
    proc = subprocess.run(
        [node, str(HARNESS), str(SCRIPT), json.dumps(scenario)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(proc.stdout)


def test_gate_appears_when_a_session_exists_but_the_agent_is_unreachable(node: str) -> None:
    result = run_gate(node, session="true", health="throw")

    assert result["afterLoad"]["gate"] is True
    assert result["insertPosition"] == "beforeend"
    assert 'role="dialog"' in result["gateHTML"]
    assert 'aria-modal="true"' in result["gateHTML"]
    assert "brew install kc-agent" in result["gateHTML"]
    # The agent must be told to trust this console's own origin.
    assert "-allowed-origins https://console.example" in result["gateHTML"]


def test_gate_appears_when_the_agent_answers_unhealthy(node: str) -> None:
    # A reachable-but-failing agent is as useless as an absent one, so a
    # non-2xx answer must gate just like a refused connection.
    result = run_gate(node, session="true", health="error")

    assert result["afterLoad"]["gate"] is True


def test_no_gate_while_the_agent_is_healthy(node: str) -> None:
    result = run_gate(node, session="true", health="ok")

    assert result["afterLoad"]["gate"] is False
    assert result["afterTick"]["gate"] is False


def test_no_gate_before_the_user_has_a_session(node: str) -> None:
    # Pre-login the console shows its own sign-in flow; gating there would
    # bury it behind an agent instruction the visitor cannot act on yet.
    result = run_gate(node, session=None, health="throw")

    assert result["afterLoad"]["gate"] is False
    # No session means no reason to probe the agent at all.
    assert result["afterLoad"]["fetchCalls"] == 0


def test_unreadable_storage_is_treated_as_no_session(node: str) -> None:
    # Private-mode browsers throw on localStorage access; the script must fail
    # open rather than gate every visitor forever.
    result = run_gate(node, storage="throws", health="throw")

    assert result["afterLoad"]["gate"] is False
    assert result["afterLoad"]["fetchCalls"] == 0


def test_gate_is_removed_once_the_agent_becomes_healthy(node: str) -> None:
    result = run_gate(node, session="true", health="throw", health2="ok")

    assert result["afterLoad"]["gate"] is True
    assert result["afterTick"]["gate"] is False


def test_repeated_failures_do_not_stack_duplicate_gates(node: str) -> None:
    result = run_gate(node, session="true", health="throw")

    assert result["afterTick"]["fetchCalls"] == 2, "poll did not probe again"
    assert result["afterTick"]["inserts"] == 1, "a second modal was stacked"


def test_agent_health_is_probed_without_credentials(node: str) -> None:
    result = run_gate(node, session="true", health="ok")

    assert result["fetchURLs"] == ["http://127.0.0.1:8585/health"] * 2
    # The agent is a local daemon: sending console cookies to it is neither
    # needed nor safe.
    assert result["fetchOptions"] == [{"credentials": "omit"}] * 2


def test_agent_health_is_polled_on_an_interval(node: str) -> None:
    result = run_gate(node, session="true", health="ok")

    assert result["timers"] == [2000]


def test_keystrokes_outside_the_gate_are_swallowed_while_it_is_up(node: str) -> None:
    result = run_gate(node, session="true", health="throw")

    assert result["keydownOutside"] is True
    # Typing inside the dialog (copying the brew command, tabbing) must work.
    assert result["keydownInside"] is False
    assert {"type": "keydown", "capture": True} in result["listeners"]


def test_keystrokes_pass_through_when_no_gate_is_up(node: str) -> None:
    # The trap is registered unconditionally at load, so it must no-op when
    # the console is usable — otherwise a healthy kiosk is unusable.
    result = run_gate(node, session="true", health="ok")

    assert result["keydownOutside"] is False
