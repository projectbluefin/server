"""Contracts for the homelab sysext: vendored manifests, the applier unit and
the render script's pins (scripts/render-homelab-manifests.py)."""

from __future__ import annotations

import base64
import configparser
import importlib.util
import ipaddress
import re
import sys
from functools import cache
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
HOMELAB = ROOT / "files" / "homelab"
MANIFESTS = HOMELAB / "manifests"
APPLIER = HOMELAB / "sysext" / "bluefin-homelab-apply"
UNIT = HOMELAB / "sysext" / "bluefin-homelab-apply.service"
ELEMENT = ROOT / "elements" / "oci" / "homelab-sysext.bst"
RENDER = ROOT / "scripts" / "render-homelab-manifests.py"
DIGEST = re.compile(r"@sha256:[0-9a-f]{64}$")

# The default component set, in apply order (monitoring is opt-in).
EXPECTED = [
    ("10-cilium", "on", "kubeadm"),
    ("20-local-path-provisioner", "on", "kubeadm,k0s"),
    ("21-nfs", "off", "kubeadm,k0s"),
    ("22-democratic-csi", "off", "kubeadm,k0s"),
    ("30-metallb", "on", "kubeadm,k0s"),
    ("40-envoy-gateway", "on", "kubeadm,k0s"),
    ("45-cert-manager", "on", "kubeadm,k0s"),
    ("50-argocd", "on", "kubeadm,k0s"),
    ("60-metrics-server", "on", "kubeadm"),
    ("61-reloader", "on", "kubeadm,k0s"),
    ("62-kured", "on", "kubeadm,k0s"),
    ("70-kube-prometheus-stack", "off", "kubeadm,k0s"),
    ("71-loki", "off", "kubeadm,k0s"),
    ("72-alloy", "off", "kubeadm,k0s"),
    ("80-gpu-operator", "off", "kubeadm,k0s"),
]


class Loader(yaml.SafeLoader):
    pass


Loader.add_constructor("tag:yaml.org,2002:value", lambda loader, node: loader.construct_scalar(node))


@cache
def docs(path: Path) -> list[dict]:
    return [d for d in yaml.load_all(path.read_text(), Loader=Loader) if d]


def manifest_files() -> list[Path]:
    return sorted(MANIFESTS.glob("*/*.yaml"))


def all_docs():
    for path in manifest_files():
        for doc in docs(path):
            yield path, doc


def index() -> list[tuple[str, str, str]]:
    rows = []
    for line in (MANIFESTS / "components").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            rows.append(tuple(line.split()))
    return rows


def strings(node):
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str):
                yield key, value
            else:
                yield from strings(value)
    elif isinstance(node, list):
        for value in node:
            if isinstance(value, str):
                yield None, value
            else:
                yield from strings(value)


def test_component_index_is_the_planned_set_in_order() -> None:
    assert index() == EXPECTED
    dirs = sorted(p.name for p in MANIFESTS.iterdir() if p.is_dir())
    assert dirs == [row[0] for row in EXPECTED], "every component directory is in the index and vice versa"


def test_component_directories_hold_only_ordered_manifests() -> None:
    for comp in MANIFESTS.iterdir():
        if not comp.is_dir():
            continue
        names = sorted(p.name for p in comp.iterdir())
        assert all(re.fullmatch(r"[0-9]{2}-[a-z0-9-]+\.yaml", n) or n == "secrets" for n in names), names
        assert any(n.startswith("10-") for n in names), f"{comp.name} has no rendered workload file"
        for path in comp.glob("00-*.yaml"):
            assert {d["kind"] for d in docs(path)} == {"CustomResourceDefinition"}
        for path in comp.glob("01-*.yaml"):
            assert {d["kind"] for d in docs(path)} == {"Namespace"}
        for path in comp.glob("[1-9]*.yaml"):
            assert "CustomResourceDefinition" not in {d["kind"] for d in docs(path)}, (
                f"{path.name}: CRDs belong in 00-crds.yaml, where the applier waits for them"
            )


def test_every_document_is_a_named_object() -> None:
    for path, doc in all_docs():
        assert doc.get("apiVersion") and doc.get("kind") and doc["metadata"].get("name"), path


def test_every_container_image_is_pinned_by_digest() -> None:
    embedded = re.compile(r"(?:docker\.io|quay\.io|ghcr\.io|registry\.k8s\.io|nvcr\.io|public\.ecr\.aws|gcr\.io)/[a-z0-9._/-]+:[A-Za-z0-9._-]+(@sha256:[0-9a-f]{64})?")
    seen = 0
    for path, doc in all_docs():
        policy = doc["kind"] == "ClusterPolicy"
        for key, value in strings(doc):
            if key == "image" and not policy:
                seen += 1
                assert DIGEST.search(value), f"{path.relative_to(ROOT)}: image {value} has no digest"
            for match in embedded.finditer(value):
                assert match.group(1), f"{path.relative_to(ROOT)}: {match.group(0)} has no digest"
        if policy:
            stack = [doc["spec"]]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if {"repository", "image", "version"} <= node.keys():
                        assert re.fullmatch(r"sha256:[0-9a-f]{64}", node["version"]), node
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    assert seen > 50


def test_images_embedded_in_config_text_are_pinned() -> None:
    # ConfigMap payloads (local-path's helper pod, Envoy Gateway's config)
    # are YAML inside strings; check their text as well.
    line = re.compile(r"^[\s-]*image:\s*\"?([^\s\"]*[/:][^\s\"]*)")
    for path in manifest_files():
        for number, text in enumerate(path.read_text().splitlines(), 1):
            m = line.match(text)
            if m and "${" not in m.group(1):
                assert DIGEST.search(m.group(1)), f"{path.relative_to(ROOT)}:{number}: {m.group(1)}"


def test_no_secret_material_is_vendored() -> None:
    for path, doc in all_docs():
        assert "-----BEGIN" not in yaml.safe_dump(doc), path
        if doc["kind"] != "Secret":
            continue
        data = {**(doc.get("data") or {}), **(doc.get("stringData") or {})}
        if doc["metadata"]["name"] == "alertmanager-kube-prometheus-stack-alertmanager":
            config = base64.b64decode(data.pop("alertmanager.yaml")).decode()
            assert not re.search(r"password|api_key|token|webhook", config, re.I), config
        assert not data, f"{path.relative_to(ROOT)}: Secret {doc['metadata']['name']} carries {sorted(data)}"
    text = "".join(p.read_text() for p in manifest_files())
    assert "prom-operator" not in text, "Grafana's chart default admin password"
    grafana = (MANIFESTS / "70-kube-prometheus-stack" / "secrets").read_text()
    assert "monitoring grafana-admin admin-user=admin admin-password=@random" in grafana


def test_no_site_addresses_outside_upstream_api_docs() -> None:
    # CRD descriptions carry upstream examples; everything else may only
    # name loopback, the wildcard, the pod CIDR and RFC 1918 network bases.
    allowed = {"0.0.0.0", "127.0.0.1", "10.0.0.0", "172.16.0.0", "192.168.0.0", "10.244.0.0"}
    ip = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")
    for path, doc in all_docs():
        if doc["kind"] == "CustomResourceDefinition":
            continue
        for addr in ip.findall(yaml.safe_dump(doc)):
            try:
                ipaddress.ip_address(addr)
            except ValueError:
                continue
            assert addr in allowed, f"{path.relative_to(ROOT)}: {doc['kind']} {doc['metadata']['name']} names {addr}"


def applier_inputs() -> set[str]:
    block = re.search(r"declare -A PATTERN=\((.*?)\n\)", APPLIER.read_text(), re.S).group(1)
    return set(re.findall(r"\[([A-Z0-9_]+)\]=", block))


def test_placeholders_are_known_applier_inputs() -> None:
    used = set()
    for path in manifest_files():
        for name in re.findall(r"\$\{HOMELAB_([A-Z0-9_]+)\}", path.read_text()):
            used.add(name)
    assert used <= applier_inputs(), used - applier_inputs()
    assert {"K8S_SERVICE_HOST", "K8S_SERVICE_PORT", "METALLB_ADDRESSES", "ACME_EMAIL", "NFS_SERVER"} <= used


def test_generated_placeholders_stay_strings() -> None:
    for path in manifest_files():
        text = path.read_text()
        if not text.startswith("# GENERATED"):
            continue
        for line in text.splitlines():
            if "${HOMELAB_" in line:
                assert re.search(r'"[^"]*\$\{HOMELAB_[A-Z0-9_]+\}[^"]*"', line), line


def test_cilium_replaces_kube_proxy_over_vxlan_with_its_api_address_injected() -> None:
    config = next(d for d in docs(MANIFESTS / "10-cilium" / "10-cilium.yaml")
                  if d["kind"] == "ConfigMap" and d["metadata"]["name"] == "cilium-config")["data"]
    assert config["kube-proxy-replacement"] == "true"
    assert config["routing-mode"] == "tunnel" and config["tunnel-protocol"] == "vxlan"
    assert config["cluster-pool-ipv4-cidr"] == "10.244.0.0/16"
    text = (MANIFESTS / "10-cilium" / "10-cilium.yaml").read_text()
    assert '"${HOMELAB_K8S_SERVICE_HOST}"' in text and '"${HOMELAB_K8S_SERVICE_PORT}"' in text
    assert "hubble-relay" in text


def workload_args(path: Path, kind: str, name: str) -> list[str]:
    doc = next(d for d in docs(path) if d["kind"] == kind and d["metadata"]["name"] == name)
    container = doc["spec"]["template"]["spec"]["containers"][0]
    return container.get("command", []) + container.get("args", [])


def test_kured_watches_the_flag_bluefin_updates_set() -> None:
    args = workload_args(MANIFESTS / "62-kured" / "10-kured.yaml", "DaemonSet", "kured")
    assert "--reboot-sentinel=/sentinel/reboot-required" in args
    ds = next(d for d in docs(MANIFESTS / "62-kured" / "10-kured.yaml") if d["kind"] == "DaemonSet")
    volume = next(v for v in ds["spec"]["template"]["spec"]["volumes"] if v["name"] == "sentinel")
    assert volume["hostPath"]["path"] == "/run"
    # The flag the base image's update path and boot deadline touch.
    assert "/run/reboot-required" in (ROOT / "files" / "os" / "update-check" / "usr" / "libexec" / "bluefin-boot-deadline").read_text()
    assert "--time-zone=${HOMELAB_KURED_TIME_ZONE}" in args


def test_metrics_server_skips_kubelet_tls_verification() -> None:
    args = workload_args(MANIFESTS / "60-metrics-server" / "10-metrics-server.yaml", "Deployment", "metrics-server")
    assert "--kubelet-insecure-tls" in args


def test_local_path_is_the_default_storage_class_on_var() -> None:
    path = MANIFESTS / "20-local-path-provisioner" / "10-local-path-provisioner.yaml"
    sc = next(d for d in docs(path) if d["kind"] == "StorageClass")
    assert sc["metadata"]["annotations"]["storageclass.kubernetes.io/is-default-class"] == "true"
    cm = next(d for d in docs(path) if d["kind"] == "ConfigMap")
    assert '"/var/lib/local-path-provisioner"' in cm["data"]["config.json"]


def test_metallb_is_layer2_with_a_pool_from_homelab_conf() -> None:
    text = (MANIFESTS / "30-metallb" / "10-metallb.yaml").read_text()
    assert "frr" not in text.lower(), "L2 mode needs neither FRR nor frr-k8s"
    pool = docs(MANIFESTS / "30-metallb" / "20-pool.yaml")
    assert [d["kind"] for d in pool] == ["IPAddressPool", "L2Advertisement"]
    assert pool[0]["spec"]["addresses"] == "${HOMELAB_METALLB_ADDRESSES}"


def test_default_gateway_and_issuers() -> None:
    gw = {d["kind"]: d for d in docs(MANIFESTS / "40-envoy-gateway" / "20-gateway.yaml")}
    assert gw["GatewayClass"]["spec"]["controllerName"] == "gateway.envoyproxy.io/gatewayclass-controller"
    assert gw["Gateway"]["spec"]["listeners"] == [
        {"name": "http", "protocol": "HTTP", "port": 80,
         "allowedRoutes": {"namespaces": {"from": "All"}}},
        {"name": "https", "protocol": "HTTPS", "port": 443,
         "tls": {"mode": "Terminate",
                  "certificateRefs": [{"name": "homelab-tls", "kind": "Secret"}]},
         "allowedRoutes": {"namespaces": {"from": "All"}}},
    ]
    crds = {d["spec"]["names"]["kind"] for d in docs(MANIFESTS / "40-envoy-gateway" / "00-crds.yaml")}
    assert {"Gateway", "GatewayClass", "HTTPRoute", "EnvoyProxy"} <= crds
    assert docs(MANIFESTS / "45-cert-manager" / "20-selfsigned-issuer.yaml")[0]["spec"] == {"selfSigned": {}}
    acme = docs(MANIFESTS / "45-cert-manager" / "21-acme-issuer.yaml")[0]["spec"]["acme"]
    assert acme["email"] == "${HOMELAB_ACME_EMAIL}", "only applied when an email is configured"


def test_gateway_certificate_covers_wildcard_domain() -> None:
    cert = docs(MANIFESTS / "45-cert-manager" / "22-gateway-cert.yaml")[0]
    assert cert["kind"] == "Certificate"
    assert cert["metadata"]["name"] == "homelab-tls"
    assert cert["metadata"]["namespace"] == "envoy-gateway-system"
    assert cert["spec"]["secretName"] == "homelab-tls"
    assert cert["spec"]["dnsNames"] == ["*.${HOMELAB_DOMAIN}", "${HOMELAB_DOMAIN}"]
    assert cert["spec"]["issuerRef"] == {"name": "${HOMELAB_ACME_ISSUER}", "kind": "ClusterIssuer"}


def test_monitoring_stack_defaults() -> None:
    text = (MANIFESTS / "70-kube-prometheus-stack" / "10-kube-prometheus-stack.yaml").read_text()
    assert "kube-proxy" not in {d["metadata"]["name"].removeprefix("kube-prometheus-stack-")
                                for d in docs(MANIFESTS / "70-kube-prometheus-stack" / "10-kube-prometheus-stack.yaml")
                                if d["kind"] == "ServiceMonitor"}
    assert "grafana-admin" in text
    loki = docs(MANIFESTS / "71-loki" / "10-loki.yaml")
    assert any(d["kind"] == "StatefulSet" and d["metadata"]["name"] == "loki" for d in loki)
    alloy = (MANIFESTS / "72-alloy" / "10-alloy.yaml").read_text()
    assert 'loki.source.journal "host"' in alloy and "loki-gateway.monitoring.svc" in alloy


def test_gpu_operator_leaves_driver_and_toolkit_to_the_sysexts() -> None:
    policy = next(d for d in docs(MANIFESTS / "80-gpu-operator" / "10-gpu-operator.yaml") if d["kind"] == "ClusterPolicy")
    spec = policy["spec"]
    assert spec["driver"]["enabled"] is False
    assert spec["toolkit"]["enabled"] is False
    assert spec["cdi"]["enabled"] is True


def test_democratic_csi_reads_its_driver_config_from_an_operator_secret() -> None:
    secrets = (MANIFESTS / "22-democratic-csi" / "secrets").read_text()
    assert ("democratic-csi democratic-csi-driver-config driver-config-file.yaml="
            "@file:/etc/bluefin/homelab.d/democratic-csi/driver-config-file.yaml") in secrets
    text = (MANIFESTS / "22-democratic-csi" / "10-democratic-csi.yaml").read_text()
    assert "secretName: democratic-csi-driver-config" in text


def test_jobs_are_named_after_their_spec() -> None:
    # Jobs are immutable; a changed spec must create a new Job.
    for path, doc in all_docs():
        if doc["kind"] == "Job":
            assert re.search(r"-[0-9a-f]{8}$", doc["metadata"]["name"]), path


@cache
def render_module():
    spec = importlib.util.spec_from_file_location("render_homelab", RENDER)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_render_script_pins_every_source_and_tool() -> None:
    render = render_module()
    assert DIGEST.search(render.HELM_IMAGE) and DIGEST.search(render.SKOPEO_IMAGE)
    assert [c.directory for c in render.COMPONENTS] == [row[0] for row in EXPECTED]
    for comp in render.COMPONENTS:
        assert re.fullmatch(r"[0-9a-f]{64}", comp.source.sha256), comp.directory
        if isinstance(comp.source, render.Chart):
            assert re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+", comp.source.version), comp.directory
        else:
            assert re.search(r"/v[0-9.]+/", comp.source.url), comp.source.url


def test_generated_files_carry_the_header_and_hand_written_ones_are_known() -> None:
    hand = {p.relative_to(MANIFESTS).as_posix() for p in manifest_files()
            if not p.read_text().startswith(render_module().GENERATED)}
    assert hand == {
        "30-metallb/20-pool.yaml",
        "40-envoy-gateway/20-gateway.yaml",
        "45-cert-manager/20-selfsigned-issuer.yaml",
        "45-cert-manager/21-acme-issuer.yaml",
        "45-cert-manager/22-gateway-cert.yaml",
        "50-argocd/20-root-app.yaml",
    }


def unit() -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read_string(UNIT.read_text())
    return parser


def test_unit_is_opt_in_and_retries_without_blocking_boot() -> None:
    u = unit()
    assert u["Unit"]["ConditionPathExists"] == "/etc/bluefin/homelab.conf"
    assert u["Service"]["EnvironmentFile"] == "/etc/bluefin/homelab.conf"
    assert u["Service"]["ExecStart"] == "/usr/libexec/bluefin-homelab-apply"
    assert u["Service"]["Type"] == "oneshot" and u["Service"]["Restart"] == "on-failure"
    assert not u.has_section("Install"), "wanted statically by the sysext, never enabled by preset"
    after = u["Unit"]["After"].split()
    assert {"kubelet.service", "k0scontroller.service", "kubeadm-init.service"} <= set(after)
    presets = "\n".join(p.read_text() for p in ROOT.glob("files/**/*.preset"))
    assert "bluefin-homelab-apply" not in presets


def test_element_stages_applier_unit_wants_and_manifests() -> None:
    text = ELEMENT.read_text()
    assert 'sysext-image: "homelab_%{image-version}"' in text
    assert 'sysext-architecture: "%{systemd-arch}"' in text
    assert "path: files/homelab/sysext" in text and "path: files/homelab/manifests" in text
    assert "for wants in kubelet.service.wants k0scontroller.service.wants" in text
    assert '"sysext%{datadir}/bluefin/homelab"' in text
    assert "%{sysext-pack}" in text
    release = (HOMELAB / "sysext" / "extension-release.homelab").read_text().splitlines()
    assert release == ["NAME=homelab", "ID=bluefin-server"]


def test_homelab_sysext_ships_in_the_signed_release_set() -> None:
    image = (ROOT / "elements" / "oci" / "bluefin-server-image.bst").read_text()
    assert "filename: oci/homelab-sysext.bst" in image
    assert "/sysext/homelab/homelab_%{image-version}.raw.zst" in image
    sbom = yaml.safe_load((ROOT / "elements" / "oci" / "bluefin-server-sbom.bst").read_text())
    assert "oci/homelab-sysext.bst" in sbom["build-depends"]
    assert '"homelab_${v}\\\\.raw\\\\.zst"' in (ROOT / "scripts" / "publish-release.sh").read_text()
    justfile = (ROOT / "Justfile").read_text()
    assert "oci/homelab-sysext.bst" in justfile
    assert "for name in homelab argo-workflows mcp kubestellar; do" in justfile
    assert "cp dist/homelab-checkout/${name}_*.raw.zst dist/sysext/" in justfile


def test_applier_never_deletes() -> None:
    code = "\n".join(l for l in APPLIER.read_text().splitlines() if not l.lstrip().startswith("#"))
    assert not re.search(r"\bdelete\b|--prune", code)
    assert "apply --server-side --force-conflicts" in code


@pytest.mark.parametrize("path", sorted((HOMELAB / "sysext").iterdir()), ids=lambda p: p.name)
def test_sysext_sources_are_reachable(path: Path) -> None:
    assert path.name in ELEMENT.read_text() or path.name.startswith("extension-release.")
