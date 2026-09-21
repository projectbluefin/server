"""Contracts for the cluster bootstrap seed and the Argo CD-owned manifest tree.

The appliance has no addon manager. Ordering, drift correction and pruning all
come from four seed phases plus one root Argo Application, so the properties
worth defending here are: every overlay still builds, every image is immutable,
and nothing in the tree is a credential someone could load.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CLUSTER = ROOT / "files" / "cluster"
SEED = CLUSTER / "seed"
MANIFESTS = CLUSTER / "manifests"
ELEMENT = ROOT / "elements" / "bluefin-server" / "os-cluster-manifests.bst"

SEED_PHASES = ("00-cilium", "10-argocd-core", "15-gitd", "20-root-app")

# Upstream manifests are fetched and sha256-pinned by the BuildStream element
# rather than vendored, so they are absent from a source checkout. Each entry
# maps the missing file to a stand-in carrying the resources the overlay
# actually acts on — the ApplicationSet controller it deletes, and every image
# name its `images:` block claims to pin. Re-derive these when the pinned
# upstream version moves: a stand-in that no longer matches upstream is how a
# silently-unpinned image would slip through.
STAND_INS: dict[str, str] = {
    "seed/10-argocd-core/core-install.yaml": """
apiVersion: apiextensions.k8s.io/v1
kind: CustomResourceDefinition
metadata:
  name: applicationsets.argoproj.io
spec:
  group: argoproj.io
  names:
    kind: ApplicationSet
    plural: applicationsets
  scope: Namespaced
  versions:
    - name: v1alpha1
      served: true
      storage: true
      schema:
        openAPIV3Schema:
          type: object
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-applicationset-controller
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-applicationset-controller
  template:
    metadata:
      labels:
        app.kubernetes.io/name: argocd-applicationset-controller
    spec:
      containers:
        - name: argocd-applicationset-controller
          image: quay.io/argoproj/argocd:v3.5.3
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-repo-server
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-repo-server
  template:
    metadata:
      labels:
        app.kubernetes.io/name: argocd-repo-server
    spec:
      containers:
        - name: argocd-repo-server
          image: quay.io/argoproj/argocd:v3.5.3
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: argocd-redis
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-redis
  template:
    metadata:
      labels:
        app.kubernetes.io/name: argocd-redis
    spec:
      containers:
        - name: redis
          image: public.ecr.aws/docker/library/redis:8.2.3-alpine
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: argocd-application-controller
spec:
  serviceName: argocd-application-controller
  selector:
    matchLabels:
      app.kubernetes.io/name: argocd-application-controller
  template:
    metadata:
      labels:
        app.kubernetes.io/name: argocd-application-controller
    spec:
      containers:
        - name: argocd-application-controller
          image: quay.io/argoproj/argocd:v3.5.3
""",
    "manifests/cert-manager/cert-manager.yaml": """
apiVersion: v1
kind: Namespace
metadata:
  name: cert-manager
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager
  namespace: cert-manager
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: cert-manager
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cert-manager
    spec:
      containers:
        - name: cert-manager-controller
          image: "quay.io/jetstack/cert-manager-controller:v1.21.2"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager-webhook
  namespace: cert-manager
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: webhook
  template:
    metadata:
      labels:
        app.kubernetes.io/name: webhook
    spec:
      containers:
        - name: cert-manager-webhook
          image: "quay.io/jetstack/cert-manager-webhook:v1.21.2"
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager-cainjector
  namespace: cert-manager
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: cainjector
  template:
    metadata:
      labels:
        app.kubernetes.io/name: cainjector
    spec:
      containers:
        - name: cert-manager-cainjector
          image: "quay.io/jetstack/cert-manager-cainjector:v1.21.2"
""",
}

KUBECTL = shutil.which("kubectl")
requires_kubectl = pytest.mark.skipif(
    KUBECTL is None, reason="kubectl is needed to build the kustomize overlays"
)


def _overlays() -> list[Path]:
    """Every directory in files/cluster/ carrying a kustomization.yaml."""
    return sorted(p.parent for p in CLUSTER.rglob("kustomization.yaml"))


@pytest.fixture(scope="module")
def tree(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """files/cluster/ with the fetch-pinned upstream manifests stood in for."""
    staged = tmp_path_factory.mktemp("cluster")
    shutil.copytree(CLUSTER, staged, dirs_exist_ok=True)
    for relative, content in STAND_INS.items():
        target = staged / relative
        assert not target.exists(), (
            f"{relative} is vendored into the repository; it is meant to be "
            "fetched and sha256-pinned by os-cluster-manifests.bst"
        )
        target.write_text(content, encoding="utf-8")
    return staged


def _build(directory: Path) -> list[dict]:
    result = subprocess.run(
        [KUBECTL, "kustomize", str(directory)],
        capture_output=True,
        text=True,
        check=False,
        # kustomize reaches the network for remote bases and helmCharts. The
        # tree is meant to be buildable on a machine with no network at all.
        env={"PATH": "/usr/bin:/bin", "HOME": str(directory), "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1"},
    )
    assert result.returncode == 0, f"kustomize build failed for {directory}:\n{result.stderr}"
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _images(docs: list[dict]) -> list[str]:
    found: list[str] = []

    def walk(node: object) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "image" and isinstance(value, str):
                    found.append(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(docs)
    return found


def test_seed_has_exactly_the_four_documented_phases() -> None:
    # bluefin-cluster-bootstrap.service applies these by name, in this order.
    # A fifth directory, or a renamed one, silently changes what first boot does.
    assert sorted(p.name for p in SEED.iterdir() if p.is_dir()) == list(SEED_PHASES)
    for phase in SEED_PHASES:
        assert (SEED / phase / "kustomization.yaml").is_file(), (
            f"{phase} is applied with `kubectl apply -k` and needs a kustomization.yaml"
        )


@requires_kubectl
@pytest.mark.parametrize("overlay", _overlays(), ids=lambda p: str(p.relative_to(CLUSTER)))
def test_every_overlay_builds_offline(overlay: Path, tree: Path) -> None:
    _build(tree / overlay.relative_to(CLUSTER))


@requires_kubectl
@pytest.mark.parametrize("overlay", [*SEED_PHASES, "."], ids=lambda name: f"seed-{name}")
def test_every_seed_image_is_digest_pinned(overlay: str, tree: Path) -> None:
    directory = tree / "manifests" if overlay == "." else tree / "seed" / overlay
    for image in _images(_build(directory)):
        assert "@sha256:" in image, f"{image} is a mutable reference in {directory.name}"


@requires_kubectl
def test_applicationset_controller_is_patched_out_but_its_crd_stays(tree: Path) -> None:
    docs = _build(tree / "seed" / "10-argocd-core")
    workloads = {(d["kind"], d["metadata"]["name"]) for d in docs}
    assert ("Deployment", "argocd-applicationset-controller") not in workloads
    assert ("CustomResourceDefinition", "applicationsets.argoproj.io") in workloads
    # Deleting the wrong thing is the failure mode that matters: Core's other
    # three workloads have to survive the patch.
    assert ("Deployment", "argocd-repo-server") in workloads
    assert ("Deployment", "argocd-redis") in workloads
    assert ("StatefulSet", "argocd-application-controller") in workloads


@requires_kubectl
def test_root_application_owns_pruning_and_drift(tree: Path) -> None:
    docs = _build(tree / "seed" / "20-root-app")
    app = next(d for d in docs if d["kind"] == "Application")
    project = next(d for d in docs if d["kind"] == "AppProject")

    automated = app["spec"]["syncPolicy"]["automated"]
    assert automated["prune"] is True
    assert automated["selfHeal"] is True

    # The manifest source must be the in-cluster bridge. An external repoURL
    # would make first boot depend on a git host being reachable.
    repo = app["spec"]["source"]["repoURL"]
    assert repo.startswith("git://bluefin-git-daemon.bluefin-system.svc.cluster.local/")
    assert repo in project["spec"]["sourceRepos"]
    assert app["spec"]["project"] == project["metadata"]["name"]

    # A project that can mint Applications or AppProjects can escape its own
    # scope, so those two kinds stay denied.
    denied = {(e["group"], e["kind"]) for e in project["spec"]["namespaceResourceBlacklist"]}
    assert ("argoproj.io", "Application") in denied
    assert ("argoproj.io", "AppProject") in denied


def test_git_daemon_serves_the_bare_repo_read_only() -> None:
    docs = list(yaml.safe_load_all((SEED / "15-gitd" / "deployment.yaml").read_text()))
    pod = next(d for d in docs if d["kind"] == "Deployment")["spec"]["template"]["spec"]
    volume = next(v for v in pod["volumes"] if v["name"] == "cluster-repo")
    mount = next(
        m for m in pod["containers"][0]["volumeMounts"] if m["name"] == "cluster-repo"
    )

    assert volume["hostPath"]["path"] == "/var/lib/bluefin/cluster.git"
    assert mount["readOnly"] is True, "Argo must never be able to write to its own source"
    assert pod["securityContext"]["runAsNonRoot"] is True


def test_no_loadable_secret_material_in_the_tree() -> None:
    # No certificate or private key ships in any image, and no Secret in the
    # tree carries a value. Credentials are generated in-cluster on first sync.
    pem_markers = ("BEGIN PRIVATE KEY", "BEGIN RSA PRIVATE KEY", "BEGIN EC PRIVATE KEY", "BEGIN CERTIFICATE")
    offenders: list[str] = []

    for path in sorted(CLUSTER.rglob("*")):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT)
        for marker in pem_markers:
            if marker in text:
                offenders.append(f"{relative}: contains {marker}")
        if path.suffix not in (".yaml", ".yml"):
            continue
        for doc in yaml.safe_load_all(text):
            if not isinstance(doc, dict) or doc.get("kind") != "Secret":
                continue
            name = doc.get("metadata", {}).get("name")
            if doc.get("data") or doc.get("stringData"):
                offenders.append(f"{relative}: Secret/{name} carries a value")

    assert offenders == []


def test_console_has_no_developer_bypass() -> None:
    # DEV_MODE made the appliance's only dashboard unauthenticated on every
    # installed machine, and the shipped jwt-secret made its sessions forgeable
    # by anyone who read this repository.
    console = (MANIFESTS / "console" / "console.yaml").read_text(encoding="utf-8")
    docs = list(yaml.safe_load_all(console))
    deployment = next(d for d in docs if d["kind"] == "Deployment")
    env = {e["name"]: e for e in deployment["spec"]["template"]["spec"]["containers"][0]["env"]}

    assert "DEV_MODE" not in env
    assert "ALLOW_DEV_MODE_IN_CLUSTER" not in env
    assert "DEV_USER_LOGIN" not in env

    jwt = env["JWT_SECRET"]["valueFrom"]["secretKeyRef"]
    assert "value" not in env["JWT_SECRET"], "the signing key must never be inline"
    assert jwt["optional"] is False, "a console that starts without a signing key is a console with no sessions"
    assert jwt["name"] == "kubestellar-console-auth"


def test_generated_credentials_are_never_overwritten() -> None:
    # Re-running either generator must not rotate a live credential: the
    # PostgreSQL password would lock the initialised database out, and the JWT
    # key would invalidate every open console session on every re-sync.
    for manifest, secret in (
        (MANIFESTS / "kubeflex" / "postgres-secret.yaml", "kubeflex-postgres"),
        (MANIFESTS / "console" / "auth-secret.yaml", "kubestellar-console-auth"),
    ):
        job = next(
            d for d in yaml.safe_load_all(manifest.read_text()) if d["kind"] == "Job"
        )
        script = job["spec"]["template"]["spec"]["containers"][0]["command"][-1]
        assert f"get secret {secret}" in script
        assert "exit 0" in script
        assert "/dev/urandom" in script


def test_element_pins_every_manifest_the_overlays_expect() -> None:
    # The overlays name these files in their `resources:`; the element is what
    # puts them there. A rename on either side is a build that succeeds and an
    # appliance that never syncs.
    element = yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))
    refs = {s["filename"]: s["ref"] for s in element["sources"] if s["kind"] == "remote"}

    assert refs == {
        "core-install.yaml": "1a87025d8eb2eae621653fd312fb9ca51df1b4b3b6992a030e3a9ef38e45c448",
        "cert-manager.yaml": "e03b668ec8675214af6b0a671699d088f2601fa3878e0dbe1b41d3feafd1879f",
    }

    install = "\n".join(element["config"]["install-commands"])
    for relative in STAND_INS:
        destination = relative.replace("seed/", "${SEED}/").replace(
            "manifests/", "${CLUSTER}/"
        )
        assert destination in install, f"element never stages {relative}"

    # core-install.yaml, not install.yaml: Core drops argocd-server and with it
    # a second authenticated web surface on the appliance.
    urls = [s["url"] for s in element["sources"] if s["kind"] == "remote"]
    assert any(u.endswith("manifests/core-install.yaml") for u in urls)
