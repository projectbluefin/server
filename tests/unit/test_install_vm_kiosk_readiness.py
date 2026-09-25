"""Contracts for `just install-vm` reaching the loopback-bound, TLS-terminating
kiosk proxy (files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml,
files/k0s/kiosk/nginx.conf)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JUSTFILE = ROOT / "Justfile"
KIOSK_PROXY_MANIFEST = (
    ROOT / "files/k0s/manifests/kubestellar/41-kubestellar-kiosk-proxy.yaml"
)


def _install_vm_recipe() -> str:
    justfile = JUSTFILE.read_text(encoding="utf-8")
    start = justfile.index("install-vm:")
    end = justfile.index("setup-kubestellar", start)
    return justfile[start:end]


def test_install_vm_drops_the_unreachable_direct_kiosk_forward() -> None:
    recipe = _install_vm_recipe()

    # A QEMU/libslirp hostfwd with an unspecified guest address is delivered
    # to the guest's DHCP address, never to 127.0.0.1, so it can never reach
    # a loopback-bound service. This forward must be gone, and the host must
    # not claim a URL it cannot reach.
    assert "hostfwd=tcp::8080-:8080" not in recipe
    assert "http://127.0.0.1:8080/" not in recipe
    assert "http://${HOST_IP" not in recipe
    assert "xdg-open" not in recipe

    # Unrelated forwards used elsewhere in the recipe must survive.
    assert "hostfwd=tcp::2222-:22" in recipe
    assert "hostfwd=tcp::6443-:6443" in recipe


def test_install_vm_probes_readiness_inside_the_guest_over_tls() -> None:
    recipe = _install_vm_recipe()

    # Readiness is probed from inside the guest, over TLS (the proxy
    # terminates TLS with a self-signed certificate), and reported on the
    # system console, which is captured to a host-side serial log file.
    assert "https://127.0.0.1:8080/healthz" in recipe
    assert "--insecure" in recipe
    assert "systemd.extra-unit.bluefin-kiosk-ready.service" in recipe
    assert "systemd.wants=bluefin-kiosk-ready.service" in recipe
    assert "-serial file:" in recipe
    assert 'SERIAL_LOG="$STATE_DIR/kiosk-serial.log"' in recipe
    assert 'grep -q "$READY_MARKER" "$SERIAL_LOG"' in recipe

    # The in-guest probe deliberately avoids parsing the /healthz response
    # body (with jq, grep, or otherwise): curl --fail already fails on a
    # non-2xx response, which is exactly "healthz ok and / returns 200",
    # and it avoids embedding quotes inside a systemd ExecStart= line, whose
    # escaping rules differ from a plain shell.
    exec_start_line = next(
        line for line in recipe.splitlines() if line.strip().startswith("ExecStart=")
    )
    assert exec_start_line.strip().startswith("ExecStart=/usr/bin/bash -c 'until curl")
    assert "jq" not in exec_start_line

    # ttyS0 must be the last (and therefore primary) console so /dev/console
    # resolves to the serial device the host captures, matching the ordering
    # test-installer-artifact already relies on for the same reason.
    assert "console=tty0 console=ttyS0,,115200 systemd.wants=bluefin-kiosk-ready.service" in recipe

    # Dies-while-waiting must still fail fast instead of polling forever.
    assert 'if ! kill -0 "$QEMU_PID" 2>/dev/null; then' in recipe


def test_install_vm_mounts_var_from_the_partlabel_credential() -> None:
    recipe = _install_vm_recipe()

    # The installed image has no fstab entry for /var and gpt-auto cannot
    # mount it, so the boot needs the same SMBIOS fstab.extra credential
    # test-installer-artifact passes. Without /var, k0s (and the kiosk proxy
    # it runs) never starts and the readiness marker never appears.
    assert (
        "io.systemd.credential.binary:fstab.extra="
        "L2Rldi9kaXNrL2J5LXBhcnRsYWJlbC92YXIgL3ZhciB4ZnMgZGVmYXVsdHMgMCAwCg=="
    ) in recipe


def test_install_vm_readiness_wait_has_a_deadline_and_diagnostics() -> None:
    recipe = _install_vm_recipe()

    # A broken guest boot must not hang forever silently: bound the wait and
    # dump the serial log on both timeout and premature QEMU exit, matching
    # test-installer-artifact.
    assert 'READY_DEADLINE_SECS="${INSTALL_VM_READY_DEADLINE:-600}"' in recipe
    assert 'if [ "$ELAPSED" -ge "$READY_DEADLINE_SECS" ]; then' in recipe
    assert recipe.count('tail -n 100 "$SERIAL_LOG" >&2') == 2


def test_install_vm_documents_ssh_tunnel_for_host_access() -> None:
    recipe = _install_vm_recipe()

    # Host access, when wanted, goes over the existing SSH hostfwd instead of
    # a direct forward the loopback-bound proxy can never receive.
    assert "ssh -p 2222" in recipe
    assert "127.0.0.1:8080" in recipe
    assert "self-signed certificate" in recipe


def test_kiosk_proxy_manifest_comment_matches_actual_reachability() -> None:
    manifest = KIOSK_PROXY_MANIFEST.read_text(encoding="utf-8")

    # The comment must not claim a hostfwd can reach a loopback-only bind;
    # a QEMU/libslirp hostfwd with an unspecified guest address never lands
    # on the guest's loopback interface.
    assert "existing hostfwd of 127.0.0.1:8080" not in manifest
    assert "hostIP: 127.0.0.1" in manifest

def test_install_vm_verifies_target_partition_layout_before_marking_complete() -> None:
    recipe = _install_vm_recipe()

    assert "bluefin-server-root-a" in recipe
    assert 'sfdisk --json "$TARGET_RAW"' in recipe
    assert 'grep -Fxq \'bluefin-server-root-a\'' in recipe
    assert 'grep -Fxq \'var\'' in recipe
    assert 'touch "$INSTALL_COMPLETE"' in recipe
