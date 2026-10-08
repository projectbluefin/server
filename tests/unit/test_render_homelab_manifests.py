"""Unit coverage for the transforms in scripts/render-homelab-manifests.py.

test_homelab_sysext.py and test_homelab_addons.py check the committed YAML
the script produced. These tests run the script's own logic (image
normalisation and digest pinning, Helm hook stripping, namespace defaulting,
Job renaming, per-chart patches, file layout and main()) offline: podman and
the network are replaced by in-process fakes.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "render-homelab-manifests.py"

_spec = importlib.util.spec_from_file_location("render_homelab_manifests_unit", SCRIPT)
assert _spec and _spec.loader
render = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = render
_spec.loader.exec_module(render)

D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


def comp(directory: str = "60-demo", namespace: str = "demo", root: Path | None = None,
         source=None) -> render.Component:
    return render.Component(
        directory, namespace,
        source or render.Manifest("https://example.invalid/v1.0.0/demo.yaml", "0" * 64),
        root=root or render.OUT,
    )


def digests(tmp_path: Path, cache: dict[str, str]) -> render.Digests:
    (tmp_path / "digests.json").write_text(json.dumps(cache))
    return render.Digests(tmp_path)


# normalize -----------------------------------------------------------------

@pytest.mark.parametrize(("ref", "expected"), [
    ("busybox:1.37.0", "docker.io/library/busybox:1.37.0"),
    ("bitnami/postgresql:17.2.0", "docker.io/bitnami/postgresql:17.2.0"),
    ("quay.io/jetstack/cert-manager-controller:v1.18.2", "quay.io/jetstack/cert-manager-controller:v1.18.2"),
    ("localhost/demo:1", "localhost/demo:1"),
    ("registry.lan:5000/team/app:2", "registry.lan:5000/team/app:2"),
])
def test_normalize_qualifies_short_names(ref: str, expected: str) -> None:
    assert render.normalize(ref) == expected


@pytest.mark.parametrize("ref", ["busybox", "quay.io/demo/app", "registry.lan:5000/app"])
def test_normalize_refuses_an_untagged_image(ref: str) -> None:
    # A port in the registry is not a tag.
    with pytest.raises(SystemExit, match="has no tag"):
        render.normalize(ref)


# image_refs / pin_images ---------------------------------------------------

def deployment(*images: str, args: list[str] | None = None) -> dict:
    containers = [{"name": f"c{i}", "image": img} for i, img in enumerate(images)]
    if args is not None:
        containers[0]["args"] = args
    return {"apiVersion": "apps/v1", "kind": "Deployment", "metadata": {"name": "demo"},
            "spec": {"template": {"spec": {"containers": containers}}}}


def test_image_refs_collects_image_keys_and_embedded_references() -> None:
    doc = deployment(
        "busybox:1.37.0",
        "quay.io/demo/pinned:v1@" + D1,
        "${HOMELAB_IMAGE}",
        "",
        args=["--helper=ghcr.io/demo/helper:v2", "--done=ghcr.io/demo/done:v3@" + D2],
    )
    assert render.image_refs(doc) == {"docker.io/library/busybox:1.37.0", "ghcr.io/demo/helper:v2"}


def test_embedded_references_need_a_known_registry_and_a_clean_left_edge() -> None:
    doc = {"kind": "ConfigMap", "data": {
        "a": "see example.com/demo/app:v1 and mirror/quay.io/demo/app:v1",
        "b": "pull nvcr.io/nvidia/cuda:12.9.1-base then quay.io/demo/app:v4",
    }}
    assert render.image_refs(doc) == {"nvcr.io/nvidia/cuda:12.9.1-base", "quay.io/demo/app:v4"}


def test_pin_images_rewrites_every_unpinned_reference(tmp_path: Path) -> None:
    doc = deployment(
        "busybox:1.37.0",
        "quay.io/demo/pinned:v1@" + D2,
        "${HOMELAB_IMAGE}",
        args=["--helper=ghcr.io/demo/helper:v2"],
    )
    ds = digests(tmp_path, {"docker.io/library/busybox:1.37.0": D1, "ghcr.io/demo/helper:v2": D2})
    pinned = render.pin_images(doc, ds)
    containers = pinned["spec"]["template"]["spec"]["containers"]
    assert [c["image"] for c in containers] == [
        "docker.io/library/busybox:1.37.0@" + D1,
        "quay.io/demo/pinned:v1@" + D2,
        "${HOMELAB_IMAGE}",
    ]
    assert containers[0]["args"] == ["--helper=ghcr.io/demo/helper:v2@" + D2]
    # The input is not mutated: main() compares the two to catch unpinned hand-written files.
    assert doc["spec"]["template"]["spec"]["containers"][0]["image"] == "busybox:1.37.0"
    assert render.pin_images(pinned, ds) == pinned


def test_cluster_policy_images_are_pinned_through_repository_image_version(tmp_path: Path) -> None:
    doc = {"apiVersion": "nvidia.com/v1", "kind": "ClusterPolicy", "metadata": {"name": "cluster-policy"},
           "spec": {
               "operator": {"repository": "nvcr.io/nvidia", "image": "gpu-operator", "version": "v26.7.1"},
               "validator": {"repository": "nvcr.io/nvidia", "image": "validator", "version": D2},
               "toolkit": [{"repository": "nvcr.io/nvidia/k8s", "image": "toolkit", "version": "v1.18.0"}],
           }}
    assert render.image_refs(doc) == {"nvcr.io/nvidia/gpu-operator:v26.7.1", "nvcr.io/nvidia/k8s/toolkit:v1.18.0"}
    ds = digests(tmp_path, {"nvcr.io/nvidia/gpu-operator:v26.7.1": D1, "nvcr.io/nvidia/k8s/toolkit:v1.18.0": D2})
    pinned = render.pin_images(doc, ds)
    assert pinned["spec"]["operator"] == {"repository": "nvcr.io/nvidia", "image": "gpu-operator", "version": D1}
    assert pinned["spec"]["validator"]["version"] == D2
    assert pinned["spec"]["toolkit"][0]["version"] == D2
    # "image" here is a bare name, never normalised into docker.io/library/.
    assert pinned["spec"]["operator"]["image"] == "gpu-operator"


# Digests ---------------------------------------------------------------------

def test_digests_resolve_only_uncached_refs_and_persist_the_cache(tmp_path: Path, monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_podman(image, work, args, entrypoint="", **kw):
        calls.append(args)
        assert image == render.SKOPEO_IMAGE and entrypoint == "sh"
        refs = (work / "refs.txt").read_text().split()
        return type("R", (), {"stdout": "".join(f"{r} {'3' * 64}\n" for r in refs)})()

    monkeypatch.setattr(render, "podman", fake_podman)
    ds = digests(tmp_path, {"quay.io/a/b:1": D1})
    ds.resolve({"quay.io/a/b:1"})
    assert calls == []
    ds.resolve({"quay.io/a/b:1", "quay.io/c/d:2"})
    assert len(calls) == 1
    assert (tmp_path / "refs.txt").read_text() == "quay.io/c/d:2\n"
    assert json.loads((tmp_path / "digests.json").read_text()) == {
        "quay.io/a/b:1": D1, "quay.io/c/d:2": "sha256:" + "3" * 64}
    assert ds.pin("quay.io/c/d:2") == "quay.io/c/d:2@sha256:" + "3" * 64
    assert ds.pin("quay.io/c/d:2@" + D1) == "quay.io/c/d:2@" + D1


def test_digests_fail_when_skopeo_leaves_a_ref_unresolved(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(render, "podman", lambda *a, **k: type("R", (), {"stdout": f"quay.io/a/b:1 {'4' * 64}\n"})())
    ds = render.Digests(tmp_path)
    with pytest.raises(SystemExit, match=r"could not resolve \['quay.io/c/d:2'\]"):
        ds.resolve({"quay.io/a/b:1", "quay.io/c/d:2"})


# postprocess -----------------------------------------------------------------

def test_postprocess_drops_test_and_delete_only_hooks_and_strips_the_rest() -> None:
    docs = [
        {"kind": "Pod", "metadata": {"name": "t", "annotations": {"helm.sh/hook": "test"}}},
        {"kind": "Job", "metadata": {"name": "d", "annotations": {"helm.sh/hook": "pre-delete, post-delete"}},
         "spec": {}},
        {"kind": "ConfigMap", "metadata": {"name": "keep", "annotations": {
            "helm.sh/hook": "pre-install,test", "helm.sh/hook-weight": "1", "other": "x"}}},
        {"kind": "ConfigMap", "metadata": {"name": "bare", "annotations": {"helm.sh/hook": "post-install"}}},
    ]
    out = render.postprocess(docs, comp())
    assert [d["metadata"]["name"] for d in out] == ["keep", "bare"]
    assert out[0]["metadata"]["annotations"] == {"other": "x"}
    assert "annotations" not in out[1]["metadata"]


def test_postprocess_namespaces_only_namespaced_kinds() -> None:
    docs = [
        {"kind": "CustomResourceDefinition", "metadata": {"name": "widgets.example.com"},
         "spec": {"scope": "Cluster", "names": {"kind": "Widget"}}},
        {"kind": "CustomResourceDefinition", "metadata": {"name": "gadgets.example.com"},
         "spec": {"scope": "Namespaced", "names": {"kind": "Gadget"}}},
        {"kind": "Widget", "metadata": {"name": "w"}},
        {"kind": "Gadget", "metadata": {"name": "g"}},
        {"kind": "ClusterIssuer", "metadata": {"name": "ci"}},
        {"kind": "ClusterRole", "metadata": {"name": "cr"}},
        {"kind": "Service", "metadata": {"name": "svc"}},
        {"kind": "Service", "metadata": {"name": "other", "namespace": "elsewhere"}},
        {"kind": "Secret"},
    ]
    out = render.postprocess(docs, comp(namespace="demo"))
    assert [d["metadata"].get("namespace") for d in out] == [
        None, None, None, "demo", None, None, "demo", "elsewhere", "demo"]


def test_postprocess_names_jobs_after_their_spec() -> None:
    def job(name: str, image: str) -> dict:
        return {"kind": "Job", "metadata": {"name": name}, "spec": {"template": {"spec": {"containers": [
            {"image": image}]}}}}

    a, b, c = render.postprocess([job("migrate", "x:1"), job("migrate", "x:2"), job("m" * 70, "x:1")], comp())
    expected = hashlib.sha256(json.dumps(job("migrate", "x:1")["spec"], sort_keys=True).encode()).hexdigest()[:8]
    assert a["metadata"]["name"] == f"migrate-{expected}"
    assert b["metadata"]["name"] != a["metadata"]["name"]
    # 54 + "-" + 8: within the 63-character label limit Jobs propagate to pods.
    assert c["metadata"]["name"] == "m" * 54 + f"-{expected}"
    assert len(c["metadata"]["name"]) == 63


def test_postprocess_drops_empty_ca_bundles_but_keeps_real_ones() -> None:
    docs = [
        {"kind": "ValidatingWebhookConfiguration", "metadata": {"name": "v"}, "webhooks": [
            {"name": "empty", "clientConfig": {"caBundle": "", "service": {"name": "s"}}},
            {"name": "set", "clientConfig": {"caBundle": "Q0E="}},
            {"name": "none"},
        ]},
        {"kind": "CustomResourceDefinition", "metadata": {"name": "a.example.com"},
         "spec": {"scope": "Namespaced", "names": {"kind": "A"},
                  "conversion": {"webhook": {"clientConfig": {"caBundle": ""}}}}},
        {"kind": "CustomResourceDefinition", "metadata": {"name": "b.example.com"},
         "spec": {"scope": "Namespaced", "names": {"kind": "B"},
                  "conversion": {"webhook": {"clientConfig": {"caBundle": "Q0E="}}}}},
    ]
    vwc, crd_a, crd_b = render.postprocess(docs, comp())
    assert vwc["webhooks"][0]["clientConfig"] == {"service": {"name": "s"}}
    assert vwc["webhooks"][1]["clientConfig"] == {"caBundle": "Q0E="}
    assert crd_a["spec"]["conversion"]["webhook"]["clientConfig"] == {}
    assert crd_b["spec"]["conversion"]["webhook"]["clientConfig"] == {"caBundle": "Q0E="}


# per-component patches ---------------------------------------------------------

def test_every_patch_targets_a_declared_component() -> None:
    declared = {c.directory for c in render.COMPONENTS + render.ADDON_COMPONENTS}
    assert set(render.PATCHES) <= declared


def test_local_path_patch_moves_storage_to_var_and_becomes_default() -> None:
    docs = [
        {"kind": "ConfigMap", "metadata": {"name": "local-path-config"}, "data": {
            "config.json": json.dumps({"nodePathMap": [
                {"node": "DEFAULT_PATH_FOR_NON_LISTED_NODES", "paths": ["/opt/local-path-provisioner"]}]}),
            "helperPod.yaml": "spec:\n  containers:\n  - image: docker.io/library/busybox\n",
        }},
        {"kind": "StorageClass", "metadata": {"name": "local-path"}},
    ]
    cm, sc = render.PATCHES["20-local-path-provisioner"](docs)
    assert json.loads(cm["data"]["config.json"])["nodePathMap"][0]["paths"] == ["/var/lib/local-path-provisioner"]
    assert "image: docker.io/library/busybox:1.37.0\n" in cm["data"]["helperPod.yaml"]
    assert sc["metadata"]["annotations"] == {"storageclass.kubernetes.io/is-default-class": "true"}


def test_argo_workflows_patch_hands_auth_to_the_client_and_pins_the_executor() -> None:
    docs = [
        {"kind": "Deployment", "metadata": {"name": "argo-server"}, "spec": {"template": {"spec": {"containers": [
            {"args": ["server"], "readinessProbe": {"httpGet": {"scheme": "HTTPS"}}}]}}}},
        {"kind": "ConfigMap", "metadata": {"name": "workflow-controller-configmap"}, "data": {"old": "x"}},
        {"kind": "ClusterRoleBinding", "metadata": {"name": "b"}, "subjects": [
            {"kind": "ServiceAccount", "name": "argo"},
            {"kind": "ServiceAccount", "name": "other", "namespace": "kept"},
            {"kind": "Group", "name": "g"}]},
    ]
    server, cm, crb = render.patch_argo_workflows(docs)
    container = server["spec"]["template"]["spec"]["containers"][0]
    assert container["args"] == ["server", "--auth-mode=client", "--secure=false"]
    assert container["readinessProbe"]["httpGet"]["scheme"] == "HTTP"
    assert cm["data"] == {"executor": "image: quay.io/argoproj/argoexec:v4.1.4\n"}
    assert [s.get("namespace") for s in crb["subjects"]] == ["argo", "kept", None]


def test_mcp_patch_replaces_the_config_and_hands_restarts_to_reloader() -> None:
    docs = [
        {"kind": "ConfigMap", "metadata": {"name": "mcp"}, "data": {"config.toml": "chart default"}},
        {"kind": "Deployment", "metadata": {"name": "mcp"}, "spec": {"template": {"metadata": {
            "annotations": {"checksum/config": "abc"}}}}},
        {"kind": "Deployment", "metadata": {"name": "mcp2"}, "spec": {"template": {"metadata": {
            "annotations": {"checksum/config": "abc", "keep": "y"}}}}},
    ]
    cm, dep, dep2 = render.patch_mcp(docs)
    assert cm["data"] == {"config.toml": render.MCP_CONFIG}
    assert "read_only = ${HOMELAB_MCP_READ_ONLY}" in render.MCP_CONFIG
    assert "annotations" not in dep["spec"]["template"]["metadata"]
    assert dep2["spec"]["template"]["metadata"]["annotations"] == {"keep": "y"}
    assert dep["metadata"]["annotations"] == {"reloader.stakater.com/auto": "true"}


def test_console_patches_drop_helm_only_jobs() -> None:
    console = render.patch_console([
        {"kind": "Deployment", "metadata": {"name": "kubestellar-console"}},
        {"kind": "Job", "metadata": {"name": "kubestellar-console-pvc-migration-1"}},
    ])
    assert [d["metadata"]["name"] for d in console] == ["kubestellar-console"]
    assert console[0]["metadata"]["annotations"] == {"reloader.stakater.com/auto": "true"}
    full = render.patch_kubestellar_full([
        {"kind": "Job", "metadata": {"name": "kubeflex-install-postgresql"}},
        {"kind": "ConfigMap", "metadata": {"name": "install-postgresql-values"}},
    ])
    assert [d["kind"] for d in full] == ["ConfigMap"]


# YAML I/O and file layout ------------------------------------------------------

def test_dump_quotes_placeholders_and_uses_literal_blocks(tmp_path: Path) -> None:
    out = tmp_path / "x.yaml"
    render.dump(out, [
        {"kind": "ConfigMap", "data": {"port": "${HOMELAB_PORT}", "script": "a\nb\n", "ragged": "a \nb\n"}},
        {"kind": "Secret"},
    ])
    text = out.read_text()
    assert text.startswith(render.GENERATED + "---\n")
    assert 'port: "${HOMELAB_PORT}"' in text
    assert "script: |\n" in text
    assert "ragged: |" not in text
    assert render.load(text) == [
        {"kind": "ConfigMap", "data": {"port": "${HOMELAB_PORT}", "script": "a\nb\n", "ragged": "a \nb\n"}},
        {"kind": "Secret"},
    ]


def test_load_skips_empty_documents_and_reads_a_bare_equals() -> None:
    assert render.load("---\n---\nkind: A\nop: =\n---\n") == [{"kind": "A", "op": "="}]


def test_write_component_splits_crds_namespaces_and_the_rest(tmp_path: Path) -> None:
    c = comp("60-demo-app", "demo", root=tmp_path)
    out = tmp_path / "60-demo-app"
    out.mkdir()
    (out / "10-stale.yaml").write_text(render.GENERATED + "kind: Old\n")
    (out / "20-hand.yaml").write_text("kind: Hand\n")
    render.write_component(c, [
        {"kind": "CustomResourceDefinition", "metadata": {"name": "a.example.com"}},
        {"kind": "Service", "metadata": {"name": "s", "namespace": "demo"}},
    ])
    assert sorted(p.name for p in out.iterdir()) == ["00-crds.yaml", "01-namespace.yaml", "10-demo-app.yaml",
                                                      "20-hand.yaml"]
    assert render.load((out / "01-namespace.yaml").read_text()) == [
        {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "demo"}}]
    assert render.load((out / "10-demo-app.yaml").read_text())[0]["kind"] == "Service"


def test_write_component_keeps_rendered_namespaces_and_skips_builtin_ones(tmp_path: Path) -> None:
    rendered_ns = {"apiVersion": "v1", "kind": "Namespace", "metadata": {"name": "demo", "labels": {"x": "y"}}}
    render.write_component(comp("60-demo", "demo", root=tmp_path), [rendered_ns])
    assert render.load((tmp_path / "60-demo" / "01-namespace.yaml").read_text()) == [rendered_ns]
    for ns in ("kube-system", "default"):
        render.write_component(comp(f"61-{ns}", ns, root=tmp_path), [{"kind": "ConfigMap"}])
        assert sorted(p.name for p in (tmp_path / f"61-{ns}").iterdir()) == [f"10-{ns}.yaml"]


# fetch / verify ----------------------------------------------------------------

def test_verify_refuses_a_mismatched_pin_and_prints_in_pins_mode(tmp_path: Path, capsys) -> None:
    f = tmp_path / "x"
    f.write_bytes(b"payload")
    actual = hashlib.sha256(b"payload").hexdigest()
    render.verify(f, actual, "x", pins_only=False)
    with pytest.raises(SystemExit, match=f"x: sha256 {actual} does not match the pin {'0' * 64}"):
        render.verify(f, "0" * 64, "x", pins_only=False)
    render.verify(f, "0" * 64, "x", pins_only=True)
    assert capsys.readouterr().out == f"x: {actual}\n"


def test_fetch_pulls_charts_from_https_and_oci_repos_once(tmp_path: Path, monkeypatch) -> None:
    pulls: list[list[str]] = []

    def fake_podman(image, work, args, entrypoint="", **kw):
        assert image == render.HELM_IMAGE
        pulls.append(args)
        name = args[1].rsplit("/", 1)[-1]
        version = args[args.index("--version") + 1]
        (work / "charts" / f"{name}-{version}.tgz").write_bytes(b"chart")

    monkeypatch.setattr(render, "podman", fake_podman)
    pin = hashlib.sha256(b"chart").hexdigest()
    https = comp(source=render.Chart("https://charts.example.invalid", "app", "1.0.0", pin))
    oci = comp(source=render.Chart("oci://ghcr.io/example/charts", "oci-app", "2.0.0", pin))
    assert render.fetch(https, tmp_path, False) == tmp_path / "charts" / "app-1.0.0.tgz"
    render.fetch(oci, tmp_path, False)
    render.fetch(https, tmp_path, False)
    assert pulls == [
        ["pull", "app", "--repo", "https://charts.example.invalid", "--version", "1.0.0", "-d", "/work/charts"],
        ["pull", "oci://ghcr.io/example/charts/oci-app", "--version", "2.0.0", "-d", "/work/charts"],
    ]


def test_helm_template_refuses_nondeterministic_output(tmp_path: Path, monkeypatch) -> None:
    outputs = iter(["a: 1\n", "a: 2\n"])
    monkeypatch.setattr(render, "podman",
                        lambda *a, **k: type("R", (), {"stdout": next(outputs)})())
    c = comp(source=render.Chart("https://x.invalid", "app", "1.0.0", "0" * 64))
    with pytest.raises(SystemExit, match="60-demo: helm template is not deterministic"):
        render.helm_template(c, tmp_path / "charts" / "app-1.0.0.tgz", tmp_path)


def test_run_exits_with_the_command_and_its_stderr() -> None:
    with pytest.raises(SystemExit, match="false failed"):
        render.run(["false"], capture_output=True)
    assert render.run(["true"]).returncode == 0


# main --------------------------------------------------------------------------

MANIFEST = """\
apiVersion: v1
kind: ServiceAccount
metadata:
  name: demo
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: demo
spec:
  template:
    spec:
      containers:
      - name: demo
        image: quay.io/demo/app:v1
"""


@pytest.fixture
def offline(tmp_path: Path, monkeypatch):
    out, addons, work = tmp_path / "manifests", tmp_path / "addons", tmp_path / "work"
    out.mkdir()
    addons.mkdir()
    pin = hashlib.sha256(MANIFEST.encode()).hexdigest()
    demo = render.Component("60-demo", "demo", render.Manifest("https://example.invalid/v1/demo.yaml", pin),
                            root=out)
    monkeypatch.setattr(render, "ROOT", tmp_path)
    monkeypatch.setattr(render, "OUT", out)
    monkeypatch.setattr(render, "ADDONS", addons)
    monkeypatch.setattr(render, "COMPONENTS", [demo])
    monkeypatch.setattr(render, "ADDON_COMPONENTS", [])
    downloads: list[str] = []

    class Resp:
        def __init__(self, url: str) -> None:
            self.url = url

        def read(self) -> bytes:
            return MANIFEST.encode()

    def urlopen(req, timeout):
        downloads.append(req.full_url)
        return Resp(req.full_url)

    monkeypatch.setattr(render.urllib.request, "urlopen", urlopen)

    def fake_podman(image, w, args, entrypoint="", **kw):
        refs = (w / "refs.txt").read_text().split()
        return type("R", (), {"stdout": "".join(f"{r} {'5' * 64}\n" for r in refs)})()

    monkeypatch.setattr(render, "podman", fake_podman)

    def main(*argv: str) -> None:
        monkeypatch.setattr(sys, "argv", ["render", "--work", str(work), *argv])
        render.main()

    return type("Offline", (), {"out": out, "addons": addons, "work": work, "main": staticmethod(main),
                                "downloads": downloads, "pin": pin})


def test_main_renders_and_pins_a_manifest_component(offline, capsys) -> None:
    offline.main()
    files = sorted(p.name for p in (offline.out / "60-demo").iterdir())
    assert files == ["01-namespace.yaml", "10-demo.yaml"]
    docs = render.load((offline.out / "60-demo" / "10-demo.yaml").read_text())
    assert [d["metadata"]["namespace"] for d in docs] == ["demo", "demo"]
    image = docs[1]["spec"]["template"]["spec"]["containers"][0]["image"]
    assert image == "quay.io/demo/app:v1@sha256:" + "5" * 64
    assert offline.downloads == ["https://example.invalid/v1/demo.yaml"]
    assert "wrote manifests:" in capsys.readouterr().out


def test_main_print_pins_downloads_without_rendering(offline, capsys) -> None:
    offline.main("--print-pins")
    assert not (offline.out / "60-demo").exists()
    assert capsys.readouterr().out == f"https://example.invalid/v1/demo.yaml: {offline.pin}\n"


def test_main_only_skips_other_components(offline) -> None:
    offline.main("--only", "99-none")
    assert offline.downloads == []
    assert list(offline.out.iterdir()) == []


def test_main_refuses_an_unpinned_hand_written_file(offline) -> None:
    hand = offline.out / "60-demo" / "20-hand.yaml"
    hand.parent.mkdir()
    hand.write_text("kind: Pod\nmetadata:\n  name: p\nspec:\n  containers:\n  - image: ghcr.io/demo/hand:v1\n")
    with pytest.raises(SystemExit, match=r"manifests/60-demo/20-hand.yaml: pin its images by digest by hand "
                                         r"\(\['ghcr.io/demo/hand:v1'\]\)"):
        offline.main()
    hand.write_text(hand.read_text().replace(":v1", ":v1@sha256:" + "6" * 64))
    offline.main()
    assert yaml.safe_load(hand.read_text())["spec"]["containers"][0]["image"].endswith("6" * 64)
