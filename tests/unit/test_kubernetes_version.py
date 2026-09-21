"""Version-axis invariants for the Kubernetes sysext.

These assert the properties that hold the axis together — that every consumer
derives its version from ``include/kubernetes.yml``, that the derived spellings
agree with each other, and that the pre-commit gate actually fires on every
file the checker reads — rather than restating the current contents of any one
file.
"""

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / ".github" / "scripts" / "check-kubernetes-version.py"

K8S_VERSION = "1.36.4"
CNI_VERSION = "1.9.1"


def _checker():
    spec = importlib.util.spec_from_file_location("check_kubernetes_version", CHECKER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _atoms():
    data = yaml.safe_load((ROOT / "include" / "kubernetes.yml").read_text())
    return data["variables"]


def test_include_declares_the_two_atoms_the_axis_is_built_from():
    variables = _atoms()
    assert variables["k8s-version"] == K8S_VERSION
    assert variables["cni-version"] == CNI_VERSION


def test_derived_tags_expand_to_the_pinned_upstream_identifiers():
    checker = _checker()
    variables = _atoms()
    atoms = {k: variables[k] for k in ("k8s-version", "cni-version")}
    assert (
        checker.expand(variables["k8s-upstream-tag"], atoms, "test")
        == f"v{K8S_VERSION}"
    )
    assert (
        checker.expand(variables["cni-upstream-tag"], atoms, "test")
        == f"v{CNI_VERSION}"
    )


def test_version_axis_is_closed_over_its_own_atoms():
    """The FSDK point release must not be able to drag Kubernetes with it.

    Every derived spelling has to resolve using only k8s-version and
    cni-version. If one reached for %{release-version} — or any other
    project.conf variable — bumping the OS would move the Kubernetes sysext.
    """
    checker = _checker()
    variables = _atoms()
    atoms = {k: variables[k] for k in ("k8s-version", "cni-version")}
    for name, value in variables.items():
        if name in atoms:
            continue
        checker.expand(value, atoms, f"include/kubernetes.yml {name}")


def test_every_node_binary_is_fetched_from_the_same_derived_release():
    """kubeadm, kubelet and kubectl skewing apart is a supported-skew violation."""
    checker = _checker()
    urls = checker.source_urls(checker.read(checker.K8S_BIN))
    fetched = {url.rsplit("/", 1)[1] for url in urls}
    assert fetched == set(checker.NODE_BINARIES)
    assert all("%{k8s-upstream-tag}" in url for url in urls)


def test_no_consumer_restates_a_literal_version():
    checker = _checker()
    for path in (
        checker.K8S_BIN,
        checker.CNI_BIN,
        checker.K8S_SYSEXT,
        checker.EXTENSION_RELEASE,
    ):
        for line in checker.read(path).splitlines():
            if line.lstrip().startswith("#"):
                continue
            assert not checker.LITERAL_VERSION_RE.search(line), (
                f"{path.relative_to(ROOT)}: {line.strip()}"
            )


def test_extension_release_defers_version_id_to_build_time():
    """A literal VERSION_ID would silently win over the generated one."""
    checker = _checker()
    text = checker.read(checker.EXTENSION_RELEASE)
    assert "NAME=kubernetes" in text
    assert not any(
        line.strip().startswith("VERSION_ID=") for line in text.splitlines()
    )


def test_checker_reads_the_component_scoped_transfer():
    checker = _checker()
    assert checker.TRANSFER == (
        ROOT / "files" / "os" / "sysupdate.kubernetes.d" / "70-kubernetes.transfer"
    )


def test_pre_commit_hook_fires_on_every_file_the_checker_reads():
    checker = _checker()
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        hook
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo.get("hooks", [])
        if hook.get("id") == "check-kubernetes-version"
    )
    selector = re.compile(hook["files"])
    consumers = [
        checker.K8S_INCLUDE,
        checker.K8S_BIN,
        checker.CNI_BIN,
        checker.K8S_SYSEXT,
        checker.EXTENSION_RELEASE,
        checker.TRANSFER,
        Path(CHECKER),
    ]
    for path in consumers:
        relative = path.relative_to(ROOT).as_posix()
        assert selector.fullmatch(relative) is not None, relative
    assert selector.fullmatch("files/os/sysupdate.d/70-kubernetes.transfer") is None


def test_repository_satisfies_the_version_invariant():
    result = subprocess.run(
        [sys.executable, str(CHECKER)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
