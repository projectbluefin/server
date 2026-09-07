from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_k0s_version_ssot():
    k0s_yml = ROOT / "include" / "k0s.yml"
    assert k0s_yml.is_file(), "include/k0s.yml missing"
    data = yaml.safe_load(k0s_yml.read_text())
    vars_ = data.get("variables", {})
    assert vars_.get("k0s-k8s-version") == "1.36.4"
    assert vars_.get("k0s-patch") == "0"
    assert vars_.get("k0s-version") == "%{k0s-k8s-version}-k0s.%{k0s-patch}"


def test_k0s_bin_element():
    bin_bst = ROOT / "elements" / "k0s" / "k0s-bin.bst"
    assert bin_bst.is_file(), "elements/k0s/k0s-bin.bst missing"
    content = bin_bst.read_text()
    assert "base/base-stack.bst" in content
    assert "github:k0sproject/k0s/releases/download/" in content
    assert "ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f" in content
