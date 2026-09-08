"""Contracts for the persistent interactive KubeStellar VM."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"


def test_install_vm_keeps_state_and_forwards_only_loopback() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("install-vm:")
    recipe = justfile[start:]

    assert "XDG_STATE_HOME" in recipe
    assert "qemu-system-x86_64" in recipe
    assert "hostfwd=tcp:127.0.0.1:8080-:8080" in recipe
    assert (
        "curl --silent --show-error --max-time 2 --output /dev/null "
        "http://127.0.0.1:8080/"
    ) in recipe
    assert "xdg-open http://127.0.0.1:8080/" in recipe
    assert "unattended" not in recipe
