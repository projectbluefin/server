"""Unit tests for .github/scripts/check-k3s-version.py.

The script is a fail-closed drift guard: ``include/k3s.yml`` is the single
source of truth for the k3s version axis, and every consumer must derive its
spelling from it rather than restate a literal. Each test repoints the
script's module-level path constants at an isolated tmp tree so the real
repository is never read.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check-k3s-version.py"

GOOD_INCLUDE = """\
variables:
  k3s-k8s-version: "1.36.2"
  k3s-patch: "1"

  k3s-upstream-tag: "v%{k3s-k8s-version}%2Bk3s%{k3s-patch}"
  k3s-version: "%{k3s-k8s-version}-k3s%{k3s-patch}"
"""

GOOD_BIN = """\
kind: manual

(@): include/k3s.yml

sources:
  - kind: remote
    url: github:k3s-io/k3s/releases/download/%{k3s-upstream-tag}/k3s
    ref: 65a55ec56c24eab44383086166ec620a491952b7e23941a49ddca6e8a4c4b4de
"""

GOOD_SYSEXT = """\
kind: manual

(@):
  - include/arch.yml
  - include/k3s.yml

config:
  install-commands:
    - |
      FNAME="k3s-%{k3s-version}.raw"
      echo "VERSION_ID=%{k3s-version}" >> extension-release.k3s
      echo "ARCHITECTURE=%{systemd-arch}" >> extension-release.k3s
"""

GOOD_EXT_RELEASE = "NAME=k3s\nID=_any\n"

GOOD_TRANSFER = """\
[Source]
Type=url-file
MatchPattern=k3s-@v.raw.zst

[Target]
MatchPattern=k3s-@v.raw
"""


def _load_module():
    spec = importlib.util.spec_from_file_location("check_k3s_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_k3s_version"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def tree(tmp_path):
    """A valid repository skeleton plus a module repointed at it."""
    files = {
        "include/k3s.yml": GOOD_INCLUDE,
        "elements/k3s/k3s-bin.bst": GOOD_BIN,
        "elements/oci/k3s-sysext.bst": GOOD_SYSEXT,
        "files/k3s/sysext/extension-release.k3s": GOOD_EXT_RELEASE,
        "files/os/sysupdate.d/70-k3s.transfer": GOOD_TRANSFER,
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    module = _load_module()
    module.ROOT = tmp_path
    module.K3S_INCLUDE = tmp_path / "include/k3s.yml"
    module.K3S_BIN = tmp_path / "elements/k3s/k3s-bin.bst"
    module.K3S_SYSEXT = tmp_path / "elements/oci/k3s-sysext.bst"
    module.EXTENSION_RELEASE = tmp_path / "files/k3s/sysext/extension-release.k3s"
    module.TRANSFER = tmp_path / "files/os/sysupdate.d/70-k3s.transfer"
    yield module, tmp_path
    sys.modules.pop("check_k3s_version", None)


def run(module):
    """Run main(); return None on success or the SystemExit message."""
    try:
        module.main()
    except SystemExit as exc:
        return str(exc.code)
    return None


def test_valid_tree_passes(tree, capsys):
    module, _ = tree
    assert run(module) is None
    out = capsys.readouterr().out
    assert "OK: k3s v1.36.2%2Bk3s1" in out
    assert "k3s-1.36.2-k3s1.raw.zst" in out
    assert "VERSION_ID=1.36.2-k3s1" in out


def test_real_repository_passes(capsys):
    """The checked-in tree must satisfy its own invariant."""
    module = _load_module()
    try:
        assert run(module) is None
        assert "OK: k3s" in capsys.readouterr().out
    finally:
        sys.modules.pop("check_k3s_version", None)


def test_missing_file_fails_closed(tree):
    module, root = tree
    (root / "include/k3s.yml").unlink()
    assert "expected file not found" in run(module)


def test_missing_atom_fails_closed(tree):
    module, root = tree
    (root / "include/k3s.yml").write_text(
        GOOD_INCLUDE.replace('k3s-patch: "1"', ""), encoding="utf-8"
    )
    assert "does not declare a 'k3s-patch:' variable" in run(module)


def test_undefined_variable_reference_fails_closed(tree):
    module, root = tree
    (root / "include/k3s.yml").write_text(
        GOOD_INCLUDE.replace("%{k3s-patch}", "%{k3s-nope}"), encoding="utf-8"
    )
    assert "undefined variable '%{k3s-nope}'" in run(module)


def test_unsafe_derived_version_fails_closed(tree):
    """A '/' in the version would break the sysupdate @v filename contract."""
    module, root = tree
    (root / "include/k3s.yml").write_text(
        GOOD_INCLUDE.replace('k3s-patch: "1"', 'k3s-patch: "1/2"'), encoding="utf-8"
    )
    assert "is not filename-safe" in run(module)


def test_hardcoded_upstream_url_fails_closed(tree):
    module, root = tree
    (root / "elements/k3s/k3s-bin.bst").write_text(
        GOOD_BIN.replace("%{k3s-upstream-tag}", "v1.36.2%2Bk3s1"), encoding="utf-8"
    )
    assert "hardcodes the upstream k3s release tag" in run(module)


def test_missing_url_fails_closed(tree):
    module, root = tree
    (root / "elements/k3s/k3s-bin.bst").write_text(
        "kind: manual\n", encoding="utf-8"
    )
    assert "declares no source 'url:'" in run(module)


def test_os_release_axis_regression_fails_closed(tree):
    """The exact regression this guard exists to prevent."""
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        GOOD_SYSEXT.replace(
            'FNAME="k3s-%{k3s-version}.raw"', 'FNAME="k3s-%{release-version}.raw"'
        ),
        encoding="utf-8",
    )
    message = run(module)
    assert "names the k3s sysext on the OS release" in message
    assert 'FNAME="k3s-%{k3s-version}.raw"' in message


def test_missing_fname_fails_closed(tree):
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        "kind: manual\n", encoding="utf-8"
    )
    assert "declares no FNAME" in run(module)


def test_underived_fname_fails_closed(tree):
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        GOOD_SYSEXT.replace(
            'FNAME="k3s-%{k3s-version}.raw"', 'FNAME="k3s-static.raw"'
        ),
        encoding="utf-8",
    )
    assert "does not derive the sysext asset name" in run(module)


def test_ungenerated_version_id_fails_closed(tree):
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        GOOD_SYSEXT.replace('echo "VERSION_ID=%{k3s-version}"', "true"),
        encoding="utf-8",
    )
    assert "does not generate VERSION_ID=" in run(module)


def test_literal_version_id_in_staged_file_fails_closed(tree):
    module, root = tree
    (root / "files/k3s/sysext/extension-release.k3s").write_text(
        GOOD_EXT_RELEASE + "VERSION_ID=v1.36.2+k3s1\n", encoding="utf-8"
    )
    assert "hardcodes a version" in run(module)


@pytest.mark.parametrize(
    "literal",
    ["v1.36.2+k3s1", "v1.36.2%2Bk3s1", "1.36.2-k3s1"],
)
def test_literal_version_in_any_spelling_fails_closed(tree, literal):
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        GOOD_SYSEXT + f'\npublic:\n  bst:\n    note: "{literal}"\n', encoding="utf-8"
    )
    assert "restates a literal k3s version" in run(module)


def test_literal_version_in_a_comment_is_allowed(tree):
    """Docs and comments may name the upstream release."""
    module, root = tree
    (root / "elements/k3s/k3s-bin.bst").write_text(
        "# SHA256 taken from v1.36.2+k3s1 sha256sum-amd64.txt\n" + GOOD_BIN,
        encoding="utf-8",
    )
    assert run(module) is None


def test_missing_transfer_pattern_fails_closed(tree):
    module, root = tree
    (root / "files/os/sysupdate.d/70-k3s.transfer").write_text(
        "[Source]\nType=url-file\n", encoding="utf-8"
    )
    assert "declares no [Source]" in run(module)


def test_asset_name_not_matching_transfer_fails_closed(tree):
    """FNAME and the sysupdate MatchPattern must stay in agreement."""
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        GOOD_SYSEXT.replace(
            'FNAME="k3s-%{k3s-version}.raw"', 'FNAME="k3s-sysext-%{k3s-version}.raw"'
        ),
        encoding="utf-8",
    )
    message = run(module)
    assert "is not the pinned k3s version" in message
    assert "'sysext-1.36.2-k3s1'" in message


def test_bumping_the_atoms_moves_every_derived_spelling(tree, capsys):
    """A k3s bump must move the asset filename on its own."""
    module, root = tree
    (root / "include/k3s.yml").write_text(
        GOOD_INCLUDE.replace('k3s-k8s-version: "1.36.2"', 'k3s-k8s-version: "1.36.3"'),
        encoding="utf-8",
    )
    assert run(module) is None
    out = capsys.readouterr().out
    assert "v1.36.3%2Bk3s1" in out
    assert "k3s-1.36.3-k3s1.raw.zst" in out
    assert "VERSION_ID=1.36.3-k3s1" in out


def test_asset_outside_transfer_pattern_fails_closed(tree):
    """An asset the MatchPattern cannot match at all is caught too."""
    module, root = tree
    (root / "elements/oci/k3s-sysext.bst").write_text(
        GOOD_SYSEXT.replace(
            'FNAME="k3s-%{k3s-version}.raw"', 'FNAME="sysext-%{k3s-version}.img"'
        ),
        encoding="utf-8",
    )
    message = run(module)
    assert "is not the pinned k3s version" in message
    assert "'@v' captures  : None" in message
