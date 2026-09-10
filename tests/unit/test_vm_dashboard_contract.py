"""Contracts for the persistent interactive KubeStellar VM."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"
CONSOLE_MANIFEST = ROOT / "files/k0s/manifests/kubestellar/40-kubestellar-console.yaml"


def test_install_vm_keeps_state_and_forwards_ports() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("install-vm:")
    recipe = justfile[start:]

    assert "XDG_STATE_HOME" in recipe
    assert "qemu-system-x86_64" in recipe
    assert "8080-:8080" in recipe
    assert (
        "curl --silent --insecure --max-time 2 --output /dev/null "
        "https://127.0.0.1:8080/"
    ) in recipe
    assert "xdg-open" in recipe
    assert "unattended" not in recipe


def test_install_vm_shows_interactive_installer_on_virtual_console() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index('echo "==> Booting the interactive installer in QEMU..."')
    end = justfile.index('touch "$INSTALL_COMPLETE"', start)
    installer_boot = justfile[start:end]

    assert "-nographic" not in installer_boot
    assert "-serial mon:stdio" not in installer_boot


def test_show_me_the_future_proves_k0s_dashboard_smoke() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    console_manifest = CONSOLE_MANIFEST.read_text(encoding="utf-8")
    start = justfile.index("show-me-the-future:")
    end = justfile.index("install-vm:")
    recipe = justfile[start:end]

    # Sysext availability / extraction
    assert "k0s" in recipe
    assert "lib/k0s/k0s.raw" in recipe

    # Repart temporary /var refresh with dummy secret injection
    assert "systemd-repart" in recipe
    assert "Type=var" in recipe
    assert "FactoryReset=yes" in recipe
    assert "CopyFiles=" in recipe
    assert "kubestellar-console-github-oauth" in recipe
    assert "namespace: kubestellar-console" in recipe
    assert "client-id:" in recipe
    assert "client-secret:" in recipe
    assert "jwt-secret:" in recipe
    assert "lib/k0s/manifests/kubestellar" in recipe
    assert "name: JWT_SECRET" in console_manifest
    assert "key: jwt-secret" in console_manifest

    # QEMU background execution with user NIC loopback forward, serial file, no monitor/display
    assert "hostfwd=tcp:127.0.0.1:8080-:8080" in recipe
    assert "-serial file:" in recipe
    assert "-monitor none" in recipe
    assert "trap" in recipe
    assert "kill -0" in recipe

    # Bounded polling with real curl checks for /healthz ok and / HTTP 200, failing fast on dead QEMU
    assert "/healthz" in recipe
    assert "curl" in recipe
    assert "status" in recipe and "ok" in recipe
    assert "200" in recipe
    assert "tail" in recipe


def test_show_me_the_future_retains_failure_artifacts() -> None:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("show-me-the-future:")
    end = justfile.index("install-vm:")
    recipe = justfile[start:end]

    assert "EXIT_STATUS=$?" in recipe
    assert '[ "$EXIT_STATUS" -eq 0 ]' in recipe
    assert 'QEMU smoke failed; retaining artifacts at $WORKDIR' in recipe
