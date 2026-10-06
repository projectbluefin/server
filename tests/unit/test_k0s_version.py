import importlib.util
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_k0s_version_ssot():
    k0s_yml = ROOT / "include" / "k0s.yml"
    assert k0s_yml.is_file(), "include/k0s.yml missing"
    data = yaml.safe_load(k0s_yml.read_text())
    vars_ = data.get("variables", {})
    # Patch releases arrive through .github/workflows/track-binaries.yml; the
    # 1.36 series only moves by hand.
    assert re.fullmatch(r"1\.36\.\d+", vars_.get("k0s-k8s-version", ""))
    assert re.fullmatch(r"\d+", vars_.get("k0s-patch", ""))
    assert vars_.get("k0s-version") == "%{k0s-k8s-version}-k0s.%{k0s-patch}"


def test_k0s_bin_element():
    bin_bst = ROOT / "elements" / "k0s" / "k0s-bin.bst"
    assert bin_bst.is_file(), "elements/k0s/k0s-bin.bst missing"
    content = bin_bst.read_text()
    assert "base/base-stack.bst" in content
    assert "github:k0sproject/k0s/releases/download/" in content
    assert re.search(r"^\s+ref: [0-9a-f]{64}$", content, re.MULTILINE)


def test_k0s_version_checker_reads_the_component_transfer():
    checker = ROOT / ".github" / "scripts" / "check-k0s-version.py"
    spec = importlib.util.spec_from_file_location("check_k0s_version", checker)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.TRANSFER == (
        ROOT / "files" / "os" / "sysupdate.k0s.d" / "70-k0s.transfer"
    )


def test_k0s_version_pre_commit_hook_selects_the_relocated_transfer():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(
        hook
        for repo in config["repos"]
        if repo.get("repo") == "local"
        for hook in repo.get("hooks", [])
        if hook.get("id") == "check-k0s-version"
    )
    selector = re.compile(hook["files"])
    assert (
        selector.fullmatch("files/os/sysupdate.k0s.d/70-k0s.transfer") is not None
    )
    assert selector.fullmatch("files/os/sysupdate.d/70-k0s.transfer") is None
