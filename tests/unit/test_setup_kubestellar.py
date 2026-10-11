"""Tests for the bluefin-kubestellar launcher and setup-kubestellar recipe contracts."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"
SCRIPT = ROOT / "files" / "bin" / "bluefin-kubestellar"


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


def test_bluefin_kubestellar_supports_ssh_tunnel() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "tunnel" in text
    assert "--tunnel" in text
    assert "--ssh-port" in text
    assert "-L" in text


def test_kc_agent_is_installed_from_the_upstream_tap() -> None:
    # kubestellar/tap owns the kc-agent formula; this repo ships no Formula/ copy.
    for text in (SCRIPT.read_text(encoding="utf-8"), JUSTFILE.read_text(encoding="utf-8")):
        assert "brew tap kubestellar/tap" in text
        assert "brew install kc-agent" in text
    assert not (ROOT / "Formula").exists()
