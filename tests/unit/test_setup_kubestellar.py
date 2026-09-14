"""Tests for bluefin-kubestellar recipe and Homebrew formula contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"
SCRIPT = ROOT / "files" / "bin" / "bluefin-kubestellar"
FORMULA_LAUNCHER = ROOT / "Formula" / "bluefin-kubestellar.rb"
FORMULA_AGENT = ROOT / "Formula" / "kc-agent.rb"


def test_bluefin_kubestellar_launcher_script_exists_and_sets_contract() -> None:
    assert SCRIPT.is_file(), "files/bin/bluefin-kubestellar must exist"
    text = SCRIPT.read_text(encoding="utf-8")
    assert 'KAGENTI_CONTROLLER_URL="${KAGENTI_CONTROLLER_URL:-none}"' in text
    assert "kc-agent" in text
    assert "-allowed-origins" in text
    assert "8585" in text


def test_justfile_setup_kubestellar_calls_launcher() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    assert "setup-kubestellar" in justfile
    assert "bluefin-kubestellar" in justfile or "kc-agent" in justfile


def test_formulas_exist_and_configure_service_or_binary() -> None:
    assert FORMULA_LAUNCHER.is_file()
    assert FORMULA_AGENT.is_file()

    agent_text = FORMULA_AGENT.read_text(encoding="utf-8")
    assert "service do" in agent_text
    assert "KAGENTI_CONTROLLER_URL" in agent_text
