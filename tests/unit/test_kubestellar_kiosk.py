"""Contracts for the KubeStellar kiosk proxy and authenticated agent gate."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
KIOSK = ROOT / "files" / "k0s" / "kiosk"
KIOSK_CONF = KIOSK / "nginx.conf"
KIOSK_JS = KIOSK / "kiosk-gate.js"
KIOSK_CSS = KIOSK / "kiosk-gate.css"
TMPFILES = ROOT / "files" / "k0s" / "sysext" / "k0s-manifests.conf"
SYSEXT = ROOT / "elements" / "oci" / "k0s-sysext.bst"
CONSOLE_MANIFEST = (
    ROOT
    / "files"
    / "k0s"
    / "manifests"
    / "kubestellar"
    / "40-kubestellar-console.yaml"
)
PROXY_MANIFEST = (
    ROOT
    / "files"
    / "k0s"
    / "manifests"
    / "kubestellar"
    / "41-kubestellar-kiosk-proxy.yaml"
)
KIOSK_TLS_SERVICE = ROOT / "files" / "k0s" / "sysext" / "k0s-kiosk-tls.service"
K0S_CONTROLLER_SERVICE = ROOT / "files" / "k0s" / "sysext" / "k0scontroller.service"
OS_STACK = ROOT / "elements" / "bluefin-server" / "os-stack.bst"


def test_kiosk_assets_are_packaged_and_seeded() -> None:
    sysext = SYSEXT.read_text(encoding="utf-8")
    tmpfiles = TMPFILES.read_text(encoding="utf-8")

    assert KIOSK_CONF.is_file()
    assert KIOSK_JS.is_file()
    assert KIOSK_CSS.is_file()
    assert "freedesktop-sdk.bst:components/openssl.bst" not in sysext
    assert "keyout" not in sysext
    assert "cp -a sysext-src/k0s-kiosk-tls.service sysext/usr/lib/systemd/system/" in sysext
    assert "path: files/k0s/kiosk" in sysext
    assert "directory: kiosk-src" in sysext
    assert "cp -a kiosk-src/. sysext/usr/share/k0s/kiosk/" in sysext
    assert "C+ /var/lib/k0s/kiosk/nginx.conf - - - - /usr/share/k0s/kiosk/nginx.conf" in tmpfiles
    assert "C+ /var/lib/k0s/kiosk/kiosk-gate.js - - - - /usr/share/k0s/kiosk/kiosk-gate.js" in tmpfiles
    assert "C+ /var/lib/k0s/kiosk/kiosk-gate.css - - - - /usr/share/k0s/kiosk/kiosk-gate.css" in tmpfiles


def test_tmpfiles_never_wipes_the_generated_tls_material() -> None:
    """A directory-level `C+ /var/lib/k0s/kiosk` would delete-then-recopy the
    whole tree from /usr/share/k0s/kiosk on every boot, which never contains
    cert.pem/key.pem -- wiping the TLS material k0s-kiosk-tls.service
    generates into that same directory. Regression guard for that collision.
    """
    directives = [
        line for line in TMPFILES.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

    assert not any("cert.pem" in line or "key.pem" in line for line in directives)
    # No directive targets the bare directory (as opposed to a file inside it).
    for line in directives:
        if line.startswith("C+"):
            assert line.split()[1] != "/var/lib/k0s/kiosk", (
                f"whole-directory C+ rule would delete cert.pem/key.pem: {line!r}"
            )


def test_proxy_injects_only_csp_safe_same_origin_assets() -> None:
    nginx = KIOSK_CONF.read_text(encoding="utf-8")

    assert (
        "proxy_pass "
        "http://kubestellar-console.kubestellar-console.svc.cluster.local:8080;"
    ) in nginx
    assert "proxy_redirect" in nginx
    assert 'proxy_set_header Accept-Encoding "";' in nginx
    assert "sub_filter_types" not in nginx
    assert (
        'sub_filter \'</head>\' '
        '\'<link rel="stylesheet" href="/kiosk-gate.css"></head>\';'
    ) in nginx
    assert (
        'sub_filter \'</body>\' '
        '\'<script defer src="/kiosk-gate.js"></script></body>\';'
    ) in nginx
    assert "Content-Security-Policy" not in nginx


def test_gate_waits_for_session_and_blocks_until_agent_health() -> None:
    script = KIOSK_JS.read_text(encoding="utf-8")
    css = KIOSK_CSS.read_text(encoding="utf-8")

    assert "kc-has-session" in script
    assert "http://127.0.0.1:8585/health" in script
    assert "brew tap kubestellar/tap && brew install kc-agent" in script
    assert "kc-agent -allowed-origins ${window.location.origin}" in script
    assert "aria-modal" in script
    assert "addEventListener('keydown'" in script
    assert "pointer-events: auto" in css
    assert "z-index: 2147483647" in css


def test_console_provides_local_and_oauth_login_options() -> None:
    console = CONSOLE_MANIFEST.read_text(encoding="utf-8")

    assert "name: DEV_MODE" in console
    assert 'value: "true"' in console
    assert "name: ALLOW_DEV_MODE_IN_CLUSTER" in console
    assert "hostPort:" not in console
    assert "name: GITHUB_CLIENT_ID" in console
    assert "name: GITHUB_CLIENT_SECRET" in console
    assert "name: kubestellar-console-github-oauth" in console
    assert "key: client-id" in console
    assert "key: client-secret" in console
    assert "optional: true" in console


def test_proxy_is_the_only_public_console_endpoint() -> None:
    proxy = PROXY_MANIFEST.read_text(encoding="utf-8")

    assert "name: kubestellar-kiosk-proxy" in proxy
    assert "hostPort: 8080" in proxy
    assert "mountPath: /etc/kubestellar-kiosk" in proxy
    assert "hostPath:\n          path: /var/lib/k0s/kiosk" in proxy
    assert "readOnly: true" in proxy
    assert (
        "nginx@sha256:62223d644fa234c3a1cc785ee14242ec47a77364226f1c811d2f669f96dc2ac8"
        in proxy
    )


def test_k0s_kiosk_tls_service_contract() -> None:
    assert KIOSK_TLS_SERVICE.is_file(), "k0s-kiosk-tls.service is missing"
    content = KIOSK_TLS_SERVICE.read_text(encoding="utf-8")

    assert "Type=oneshot" in content
    assert "Before=k0scontroller.service" in content
    assert "RequiresMountsFor=/var/lib/k0s" in content
    assert "After=network-online.target systemd-tmpfiles-setup.service" in content
    assert "StateDirectory=k0s" in content
    assert "chmod 0600 /var/lib/k0s/kiosk/key.pem" in content
    assert "chmod 0644 /var/lib/k0s/kiosk/cert.pem" in content
    assert "/CN=KubeStellar Console" in content
    assert "DNS:localhost,DNS:*.local,IP:127.0.0.1" in content
    assert "ip -o addr show scope global" in content
    assert (
        "test -s /var/lib/k0s/kiosk/key.pem && "
        "test -s /var/lib/k0s/kiosk/cert.pem && exit 0"
    ) in content


def test_k0scontroller_orders_after_kiosk_tls() -> None:
    assert K0S_CONTROLLER_SERVICE.is_file(), "k0scontroller.service is missing"
    content = K0S_CONTROLLER_SERVICE.read_text(encoding="utf-8")

    assert "k0s-kiosk-tls.service" in content
    assert "After=network-online.target k0s-kiosk-tls.service" in content
    assert "Wants=network-online.target k0s-kiosk-tls.service" in content


def test_os_stack_includes_openssl() -> None:
    content = OS_STACK.read_text(encoding="utf-8")
    assert "freedesktop-sdk.bst:components/openssl.bst" in content
