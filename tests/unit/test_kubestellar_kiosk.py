"""Contracts for the KubeStellar kiosk proxy and authenticated agent gate."""

import posixpath
import re
import subprocess
from pathlib import Path

import yaml

from _systemd import SystemdFile, tmpfiles

ROOT = Path(__file__).resolve().parents[2]
KIOSK = ROOT / "files" / "k0s" / "kiosk"
KIOSK_CONF = KIOSK / "nginx.conf"
KIOSK_JS = KIOSK / "kiosk-gate.js"
KIOSK_CSS = KIOSK / "kiosk-gate.css"
TMPFILES = ROOT / "files" / "kubestellar" / "sysext" / "k0s-manifests.conf"
SYSEXT = ROOT / "elements" / "oci" / "kubestellar-sysext.bst"
K0S_SYSEXT = ROOT / "elements" / "oci" / "k0s-sysext.bst"
SEED = ROOT / "files" / "kubestellar" / "sysext" / "kubestellar-seed.service"
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


def local_sources(element: Path) -> list[dict]:
    data = yaml.safe_load(element.read_text(encoding="utf-8"))
    return [s for s in data["sources"] if s["kind"] == "local"]


def deployment_pod(manifest: Path, name: str) -> dict:
    docs = [d for d in yaml.safe_load_all(manifest.read_text(encoding="utf-8")) if d]
    (deployment,) = [d for d in docs if d["kind"] == "Deployment" and d["metadata"]["name"] == name]
    return deployment["spec"]["template"]["spec"]


def test_kiosk_assets_are_packaged_and_seeded() -> None:
    sysext = SYSEXT.read_text(encoding="utf-8")

    assert KIOSK_CONF.is_file()
    assert KIOSK_JS.is_file()
    assert KIOSK_CSS.is_file()
    assert {"kind": "local", "path": "files/k0s/kiosk", "directory": "kiosk-src"} in local_sources(SYSEXT)
    assert 'cp -a kiosk-src/. "${root}/share/k0s/kiosk/"' in sysext
    seeded = [rule for rule in tmpfiles(TMPFILES) if rule.path == "/var/lib/k0s/kiosk"]
    assert [(rule.type, rule.argument) for rule in seeded] == [("C+", "/usr/share/k0s/kiosk")]
    k0s_sources = [s["path"] for s in local_sources(K0S_SYSEXT)]
    assert "files/k0s/sysext" in k0s_sources
    assert "files/k0s/kiosk" not in k0s_sources, (
        "the kiosk ships in the opt-in KubeStellar sysext, not with k0s"
    )


def test_kiosk_tls_key_is_generated_per_node_not_shipped(tmp_path: Path) -> None:
    sysext = SYSEXT.read_text(encoding="utf-8")
    assert "openssl req" not in sysext, "a public sysext must not carry a private key"
    assert "key material in a public sysext" in sysext

    scripts = [
        argv[2]
        for argv in SystemdFile(SEED).commands()
        if posixpath.basename(argv[0]) == "sh" and argv[1:2] == ["-c"] and "openssl" in argv[2]
    ]
    assert len(scripts) == 1, "expected one sh -c command generating the kiosk key"
    assert "/var/lib/k0s/kiosk" in scripts[0] and "/usr/bin/openssl" in scripts[0]
    kiosk = tmp_path / "kiosk"
    kiosk.mkdir()
    openssl = tmp_path / "openssl"
    openssl.write_text(
        '#!/bin/sh\necho "$@" >> "$CALLS"\n'
        'while [ $# -gt 0 ]; do case "$1" in -keyout|-out) : > "$2";; esac; shift; done\n',
        encoding="utf-8",
    )
    openssl.chmod(0o755)
    calls = tmp_path / "calls"
    script = scripts[0].replace("/var/lib/k0s/kiosk", str(kiosk)).replace("/usr/bin/openssl", str(openssl))

    def seed() -> list[str]:
        subprocess.run(["sh", "-c", script], env={"CALLS": str(calls), "PATH": "/usr/bin:/bin"}, check=True)
        return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []

    first = seed()
    assert len(first) == 1 and f"-keyout {kiosk}/key.pem" in first[0]
    assert ((kiosk / "key.pem").stat().st_mode & 0o077) == 0, "the private key must not be group/world readable"
    assert ((kiosk / "cert.pem").stat().st_mode & 0o777) == 0o644
    (kiosk / "key.pem").write_text("existing node key", encoding="utf-8")
    assert seed() == first, "an existing key must never be regenerated"


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
    assert (
        'KAGENTI_CONTROLLER_URL="none" kc-agent -allowed-origins'
        " ${window.location.origin}"
    ) in script
    assert "aria-modal" in script
    assert "addEventListener('keydown'" in script
    assert "pointer-events: auto" in css
    assert "z-index: 2147483647" in css


def test_console_provides_local_and_oauth_login_options() -> None:
    pod = deployment_pod(CONSOLE_MANIFEST, "kubestellar-console")
    (console,) = [c for c in pod["containers"] if c["name"] == "console"]
    env = {e["name"]: e for e in console["env"]}

    # #193: on first boot the console must read the local k0s cluster directly
    # (no connected kc-agent yet) and skip the onboarding questionnaire.
    # SKIP_ONBOARDING skips the questionnaire, not sign-in; sign-in is bypassed
    # by DEV_MODE/DEV_USER_LOGIN.
    for flag in ("DEV_MODE", "ALLOW_DEV_MODE_IN_CLUSTER", "SKIP_ONBOARDING", "NO_LOCAL_AGENT"):
        assert env[flag].get("value") == "true", flag
    assert env["POD_NAMESPACE"].get("value") == "kubestellar-console"
    assert pod["serviceAccountName"] == "kubestellar-console"
    for name, key in (("GITHUB_CLIENT_ID", "client-id"), ("GITHUB_CLIENT_SECRET", "client-secret")):
        assert env[name]["valueFrom"]["secretKeyRef"] == {
            "name": "kubestellar-console-github-oauth",
            "key": key,
            "optional": True,
        }, name

    # Only the kiosk proxy may be reachable from the node.
    assert not pod.get("hostNetwork")
    assert not [p for c in pod["containers"] for p in c.get("ports", []) if "hostPort" in p]
    docs = [d for d in yaml.safe_load_all(CONSOLE_MANIFEST.read_text(encoding="utf-8")) if d]
    assert all(d["spec"].get("type", "ClusterIP") == "ClusterIP" for d in docs if d["kind"] == "Service")


def test_proxy_is_the_only_public_console_endpoint() -> None:
    pod = deployment_pod(PROXY_MANIFEST, "kubestellar-kiosk-proxy")
    (proxy,) = pod["containers"]

    published = [(p.get("hostIP"), p["hostPort"]) for p in proxy["ports"] if "hostPort" in p]
    assert published == [("127.0.0.1", 8080)], "publish the kiosk on loopback only"
    assert re.fullmatch(r"docker\.io/library/nginx@sha256:[0-9a-f]{64}", proxy["image"]), proxy["image"]
    (mount,) = [m for m in proxy["volumeMounts"] if m["mountPath"] == "/etc/kubestellar-kiosk"]
    assert mount.get("readOnly") is True
    (volume,) = [v for v in pod["volumes"] if v["name"] == mount["name"]]
    assert volume["hostPath"]["path"] == "/var/lib/k0s/kiosk"


def test_console_rbac_reads_only_the_local_cluster() -> None:
    rbac = (
        ROOT
        / "files"
        / "k0s"
        / "manifests"
        / "kubestellar"
        / "42-kubestellar-console-rbac.yaml"
    ).read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(rbac))
    kinds = [d.get("kind") for d in docs if d]
    assert kinds == [
        "ServiceAccount",
        "ClusterRole",
        "ClusterRoleBinding",
    ]

    sa = next(d for d in docs if d["kind"] == "ServiceAccount")
    assert sa["metadata"]["namespace"] == "kubestellar-console"

    role = next(d for d in docs if d["kind"] == "ClusterRole")
    # Read-only: never grant write verbs to the console's account.
    for rule in role["rules"]:
        assert set(rule["verbs"]) <= {"get", "list", "watch"}
    resources = {r for rule in role["rules"] for r in rule["resources"]}
    assert {"nodes", "namespaces", "pods"} <= resources
    # Kubernetes silently ignores resource names that do not exist in the named
    # apiGroup, so a typo (e.g. "limitquotas") drops the grant with no error.
    # Pin every name to the real resource for its group.
    known_resources = {
        "": {
            "configmaps",
            "endpoints",
            "events",
            "limitranges",
            "namespaces",
            "nodes",
            "persistentvolumeclaims",
            "persistentvolumes",
            "pods",
            "replicationcontrollers",
            "resourcequotas",
            "serviceaccounts",
            "services",
        },
        "apps": {"daemonsets", "deployments", "replicasets", "statefulsets"},
        "batch": {"cronjobs", "jobs"},
    }
    for rule in role["rules"]:
        for group in rule["apiGroups"]:
            assert group in known_resources, f"unexpected apiGroup {group!r}"
            unknown = set(rule["resources"]) - known_resources[group]
            assert not unknown, f"not real resources in apiGroup {group!r}: {unknown}"
    # The kiosk dashboard never needs secrets; keep them out of the grant.
    assert "secrets" not in resources

    binding = next(d for d in docs if d["kind"] == "ClusterRoleBinding")
    assert binding["roleRef"]["kind"] == "ClusterRole"
    assert binding["roleRef"]["name"] == role["metadata"]["name"]
    subject = binding["subjects"][0]
    assert subject["kind"] == "ServiceAccount"
    assert subject["name"] == "kubestellar-console"
    assert subject["namespace"] == "kubestellar-console"
