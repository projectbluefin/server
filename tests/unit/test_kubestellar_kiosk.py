"""Contracts for the KubeStellar kiosk proxy and its authenticated agent gate.

The kiosk is the appliance's only dashboard and its only public port. What is
defended here is that it is reachable, that it terminates TLS with material it
generated itself, that the gate it injects actually reaches the browser, and
that it reads nothing off the node.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
KIOSK = ROOT / "files" / "cluster" / "manifests" / "kiosk"
ASSETS = KIOSK / "assets"
NGINX_CONF = ASSETS / "nginx.conf"
GATE_JS = ASSETS / "kiosk-gate.js"
GATE_CSS = ASSETS / "kiosk-gate.css"


def _doc(path: Path, kind: str) -> dict:
    return next(d for d in yaml.safe_load_all(path.read_text(encoding="utf-8")) if d["kind"] == kind)


def test_assets_are_delivered_from_the_cluster_not_the_node() -> None:
    # These three files used to arrive through a hostPath mount seeded by
    # tmpfiles.d, which meant the workload's configuration lived outside the
    # cluster and could not be reconciled or rolled.
    kustomization = yaml.safe_load((KIOSK / "kustomization.yaml").read_text(encoding="utf-8"))
    generator = kustomization["configMapGenerator"][0]
    assert sorted(generator["files"]) == [
        "assets/kiosk-gate.css",
        "assets/kiosk-gate.js",
        "assets/nginx.conf",
    ]

    pod = _doc(KIOSK / "deployment.yaml", "Deployment")["spec"]["template"]["spec"]
    assert all("hostPath" not in volume for volume in pod["volumes"])
    assets = next(v for v in pod["volumes"] if v["name"] == "assets")
    assert assets["configMap"]["name"] == generator["name"]


def test_nginx_writes_only_to_mounted_volumes() -> None:
    # The container root filesystem is read-only. nginx opens its pid file and
    # its proxy scratch paths at startup, so any path that is not on a writable
    # mount is a pod that crash-loops before it ever serves a request.
    container = _doc(KIOSK / "deployment.yaml", "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert container["securityContext"]["readOnlyRootFilesystem"] is True

    writable = {
        mount["mountPath"]
        for mount in container["volumeMounts"]
        if not mount.get("readOnly", False)
    }
    assert writable, "a read-only root filesystem needs somewhere for nginx to write"

    conf = NGINX_CONF.read_text(encoding="utf-8")
    paths = re.findall(r"^\s*(?:pid|\w+_temp_path)\s+(\S+?);", conf, flags=re.MULTILINE)
    assert paths, "nginx.conf declares no pid or temp paths to check"
    for path in paths:
        assert any(path.startswith(f"{root}/") for root in writable), (
            f"{path} is not on a writable mount ({sorted(writable)})"
        )


def test_proxy_injects_the_gate_same_origin_into_live_html() -> None:
    conf = NGINX_CONF.read_text(encoding="utf-8")

    # The gate is injected by rewriting the console's HTML. nginx cannot rewrite
    # a compressed response body, so upstream compression has to be refused or
    # sub_filter silently does nothing and the gate never appears.
    assert 'proxy_set_header Accept-Encoding "";' in conf
    assert '<link rel="stylesheet" href="/kiosk-gate.css">' in conf
    assert '<script defer src="/kiosk-gate.js"></script>' in conf

    # Both assets are served by this proxy on its own origin, so no CSP the
    # console sets can block them and no third-party host is contacted.
    for asset in ("kiosk-gate.js", "kiosk-gate.css"):
        assert f"location = /{asset} {{" in conf
        assert f"alias /etc/kubestellar-kiosk/assets/{asset};" in conf

    # CoreDNS on the kubeadm service CIDR; resolved at request time so the
    # console Service moving does not require restarting the proxy.
    assert "resolver 10.96.0.10" in conf
    assert (
        "http://kubestellar-console.kubestellar-console.svc.cluster.local:8080" in conf
    )


def test_gate_blocks_the_console_until_the_agent_is_reachable() -> None:
    script = GATE_JS.read_text(encoding="utf-8")
    css = GATE_CSS.read_text(encoding="utf-8")

    assert "kc-has-session" in script
    assert "http://127.0.0.1:8585/health" in script
    assert "aria-modal" in script
    # The overlay has to actually trap interaction, or it is decoration.
    assert "addEventListener('keydown'" in script
    assert "pointer-events: auto" in css
    assert "z-index: 2147483647" in css


def test_tls_is_issued_in_cluster_and_short_lived() -> None:
    # Replaces the 10-year self-signed key that was generated at image build
    # time and was therefore identical on every installed appliance.
    certificate = _doc(KIOSK / "certificate.yaml", "Certificate")["spec"]
    assert certificate["issuerRef"]["kind"] == "ClusterIssuer"
    assert certificate["issuerRef"]["name"] == "bluefin-ca"
    assert certificate["privateKey"]["rotationPolicy"] == "Always"

    hours = int(certificate["duration"].removesuffix("h"))
    assert hours <= 2400, "the kiosk certificate must stay under 100 days"
    assert int(certificate["renewBefore"].removesuffix("h")) < hours

    container = _doc(KIOSK / "deployment.yaml", "Deployment")["spec"]["template"]["spec"]["containers"][0]
    tls = next(m for m in container["volumeMounts"] if m["name"] == "tls")
    conf = NGINX_CONF.read_text(encoding="utf-8")
    assert f"ssl_certificate {tls['mountPath']}/tls.crt;" in conf
    assert f"ssl_certificate_key {tls['mountPath']}/tls.key;" in conf
    assert "listen 8080 ssl;" in conf
    # Anyone arriving over plain HTTP on the TLS port gets redirected rather
    # than an nginx error page.
    assert "error_page 497 https://$http_host$request_uri;" in conf


def test_proxy_is_published_on_every_interface() -> None:
    # Binding hostIP 127.0.0.1 made the console unreachable from the LAN and
    # from anything but a single QEMU hostfwd. The endpoint is HTTPS-only and
    # the console behind it authenticates.
    container = _doc(KIOSK / "deployment.yaml", "Deployment")["spec"]["template"]["spec"]["containers"][0]
    port = next(p for p in container["ports"] if p.get("hostPort"))
    assert port["hostPort"] == 8080
    assert port["containerPort"] == 8080
    assert "hostIP" not in port


def test_proxy_image_is_immutable() -> None:
    container = _doc(KIOSK / "deployment.yaml", "Deployment")["spec"]["template"]["spec"]["containers"][0]
    assert "@sha256:" in container["image"]
