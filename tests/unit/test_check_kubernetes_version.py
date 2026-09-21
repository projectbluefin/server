"""Unit coverage for .github/scripts/check-kubernetes-version.py.

The script is the only gate holding the Kubernetes version axis together. It is
run by ``just validate`` and by the ``check-kubernetes-version`` pre-commit
hook, so every fail-closed branch needs direct coverage: without it a branch
can regress to fail-open and nothing notices until the sysext silently stops
updating on deployed hosts.

Covered here: ``read()``, ``scalar()``, ``expand()``, ``fail()``,
``source_urls()`` and each rejection path of ``main()`` — non-filename-safe
version, missing/hardcoded node-binary URLs, missing/hardcoded CNI URL,
missing/OS-axis/underived ``FNAME``, missing generated ``VERSION_ID``, missing
``/usr/local/share`` version stamps, a hardcoded ``VERSION_ID=`` in
extension-release.kubernetes, literal versions restated in any consumer, a
missing sysupdate ``MatchPattern``, and an asset name whose ``@v`` capture
disagrees with ``%{k8s-version}``.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check-kubernetes-version.py"

GOOD_INCLUDE = """variables:
  k8s-version: "1.36.4"
  cni-version: "1.9.1"

  k8s-upstream-tag: "v%{k8s-version}"
  cni-upstream-tag: "v%{cni-version}"
"""

GOOD_BIN = """kind: manual
sources:
  - kind: remote
    url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubectl
  - kind: remote
    url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubeadm
  - kind: remote
    url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubelet
"""

GOOD_CNI = """kind: manual
sources:
  - kind: tar
    url: github:containernetworking/plugins/releases/download/%{cni-upstream-tag}/cni-plugins-linux-amd64-%{cni-upstream-tag}.tgz
"""

GOOD_SYSEXT = """kind: manual
config:
  install-commands:
    - |
      FNAME="kubernetes-%{k8s-version}.raw"
      echo "%{k8s-version}" > sysext/usr/local/share/kubernetes-version
      echo "%{cni-version}" > sysext/usr/local/share/kubernetes-cni-version
      echo "VERSION_ID=%{k8s-version}" >> extension-release.kubernetes
"""

GOOD_EXTENSION_RELEASE = "NAME=kubernetes\nID=_any\n"

GOOD_TRANSFER = """[Source]
Type=url-file
MatchPattern=kubernetes-@v.raw.zst

[Target]
MatchPattern=kubernetes-@v.raw
"""

EXPECTED_VERSION = "1.36.4"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "check_kubernetes_version", SCRIPT_PATH
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_kubernetes_version"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path):
    """Fresh module instance with its path constants rooted at tmp_path.

    ``ROOT`` and the six consumer paths are module-level globals derived from
    the script's own location, so each test gets a re-imported copy repointed at
    an isolated tree pre-populated with a passing configuration.
    """
    module = _load_module()
    module.ROOT = tmp_path
    module.K8S_INCLUDE = tmp_path / "include" / "kubernetes.yml"
    module.K8S_BIN = tmp_path / "elements" / "kubernetes" / "kubernetes-bin.bst"
    module.CNI_BIN = tmp_path / "elements" / "kubernetes" / "cni-plugins.bst"
    module.K8S_SYSEXT = tmp_path / "elements" / "oci" / "kubernetes-sysext.bst"
    module.EXTENSION_RELEASE = (
        tmp_path / "files" / "kubernetes" / "sysext" / "extension-release.kubernetes"
    )
    module.TRANSFER = (
        tmp_path / "files" / "os" / "sysupdate.kubernetes.d" / "70-kubernetes.transfer"
    )
    for path, text in (
        (module.K8S_INCLUDE, GOOD_INCLUDE),
        (module.K8S_BIN, GOOD_BIN),
        (module.CNI_BIN, GOOD_CNI),
        (module.K8S_SYSEXT, GOOD_SYSEXT),
        (module.EXTENSION_RELEASE, GOOD_EXTENSION_RELEASE),
        (module.TRANSFER, GOOD_TRANSFER),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    yield module
    sys.modules.pop("check_kubernetes_version", None)


def _run(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    return str(excinfo.value)


# --- read() ---------------------------------------------------------------


def test_read_returns_file_contents(checker, tmp_path):
    target = tmp_path / "include" / "kubernetes.yml"
    assert checker.read(target) == GOOD_INCLUDE


def test_read_exits_on_missing_file(checker, tmp_path):
    missing = tmp_path / "include" / "gone.yml"
    with pytest.raises(SystemExit) as excinfo:
        checker.read(missing)
    assert "expected file not found" in str(excinfo.value)
    assert "include/gone.yml" in str(excinfo.value)


# --- scalar() -------------------------------------------------------------


def test_scalar_reads_double_quoted_value(checker):
    assert checker.scalar(GOOD_INCLUDE, "cni-version", "where") == "1.9.1"


def test_scalar_reads_single_quoted_value(checker):
    text = "variables:\n  cni-version: '1.9.2'\n"
    assert checker.scalar(text, "cni-version", "where") == "1.9.2"


def test_scalar_ignores_unquoted_value(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.scalar(
            "variables:\n  cni-version: 1.9.1\n",
            "cni-version",
            "include/kubernetes.yml",
        )
    assert "does not declare a 'cni-version:' variable" in str(excinfo.value)


def test_scalar_exits_when_name_absent(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.scalar(GOOD_INCLUDE, "k8s-nope", "include/kubernetes.yml")
    assert "include/kubernetes.yml does not declare a 'k8s-nope:' variable" in str(
        excinfo.value
    )


# --- expand() -------------------------------------------------------------


def test_expand_returns_literal_unchanged(checker):
    assert checker.expand("1.36.4", {}, "where") == "1.36.4"


def test_expand_substitutes_nested_references(checker):
    variables = {"a": "%{b}", "b": "leaf"}
    assert checker.expand("%{a}", variables, "where") == "leaf"


def test_expand_exits_on_undefined_reference(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.expand("%{missing}", {}, "include/kubernetes.yml x")
    assert "references undefined variable '%{missing}'" in str(excinfo.value)


def test_expand_exits_on_circular_reference(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.expand("%{a}", {"a": "%{b}", "b": "%{a}"}, "include/kubernetes.yml x")
    assert "circular variable reference" in str(excinfo.value)


# --- fail() ---------------------------------------------------------------


def test_fail_reports_problem_and_fix(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.fail("something drifted", "do the thing")
    message = str(excinfo.value)
    assert "ERROR: something drifted" in message
    assert "Fix: do the thing" in message


# --- source_urls() --------------------------------------------------------


def test_source_urls_collects_every_declared_url(checker):
    assert checker.source_urls(GOOD_BIN) == [
        "k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubectl",
        "k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubeadm",
        "k8s:%{k8s-upstream-tag}/bin/linux/amd64/kubelet",
    ]


def test_source_urls_returns_empty_without_sources(checker):
    assert checker.source_urls("kind: manual\nsources: []\n") == []


# --- module-level regexes -------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    ["1.36.4", "v1.36.4", "1.9.1", "release~1^2"],
)
def test_safe_version_re_accepts_filename_safe_versions(checker, candidate):
    assert checker.SAFE_VERSION_RE.match(candidate)


@pytest.mark.parametrize("candidate", ["1.36.4 rc1", "1.36.4/0", "", "a:b"])
def test_safe_version_re_rejects_unsafe_versions(checker, candidate):
    assert not checker.SAFE_VERSION_RE.match(candidate)


@pytest.mark.parametrize(
    "candidate",
    [
        "url: k8s:v1.36.4/bin/linux/amd64/kubeadm",
        "cni-plugins-linux-amd64-v1.9.1.tgz",
        "FNAME=kubernetes-1.36.4.raw",
    ],
)
def test_literal_version_re_matches_every_spelling(checker, candidate):
    assert checker.LITERAL_VERSION_RE.search(candidate)


@pytest.mark.parametrize(
    "candidate",
    [
        "%{k8s-upstream-tag}",
        'FNAME="kubernetes-%{k8s-version}.raw"',
        "ref: b98f74a0f8522f0a83867178729c1aa70f2158f90c45a2ca8fa791db1c76b303",
        "install -D -m 0755 cni-src/host-local",
    ],
)
def test_literal_version_re_ignores_derived_and_incidental_text(checker, candidate):
    assert not checker.LITERAL_VERSION_RE.search(candidate)


# --- main(): the passing path --------------------------------------------


def test_main_accepts_a_fully_derived_configuration(checker, capsys):
    checker.main()
    out = capsys.readouterr().out
    assert "OK: Kubernetes v1.36.4 and CNI plugins v1.9.1" in out
    assert f"asset kubernetes-{EXPECTED_VERSION}.raw.zst" in out
    assert f"VERSION_ID={EXPECTED_VERSION}" in out


def test_main_tolerates_literal_version_inside_comments(checker, capsys):
    checker.K8S_BIN.write_text(
        "# pinned from the v1.36.4 release notes\n" + GOOD_BIN,
        encoding="utf-8",
    )
    checker.main()
    assert "OK: Kubernetes" in capsys.readouterr().out


# --- main(): version safety ----------------------------------------------


def test_main_rejects_version_that_is_not_filename_safe(checker):
    checker.K8S_INCLUDE.write_text(
        GOOD_INCLUDE.replace('k8s-version: "1.36.4"', 'k8s-version: "1.36.4 rc1"'),
        encoding="utf-8",
    )
    assert "is not filename-safe" in _run(checker)


# --- main(): node binary download URLs -----------------------------------


@pytest.mark.parametrize("binary", ["kubectl", "kubeadm", "kubelet"])
def test_main_rejects_a_missing_node_binary_url(checker, binary):
    checker.K8S_BIN.write_text(
        "\n".join(
            line for line in GOOD_BIN.splitlines() if not line.endswith(f"/{binary}")
        )
        + "\n",
        encoding="utf-8",
    )
    message = _run(checker)
    assert "declares no source 'url:'" in message
    assert f"'/{binary}'" in message


def test_main_rejects_hardcoded_upstream_tag_in_node_binary_url(checker):
    checker.K8S_BIN.write_text(
        GOOD_BIN.replace("%{k8s-upstream-tag}", "v1.36.4", 1), encoding="utf-8"
    )
    assert "hardcodes the upstream\n  Kubernetes release tag" in _run(checker)


# --- main(): CNI plugins download URL ------------------------------------


def test_main_rejects_missing_cni_url(checker):
    checker.CNI_BIN.write_text("kind: manual\nsources: []\n", encoding="utf-8")
    assert "cni-plugins.bst declares no source 'url:'" in _run(checker)


def test_main_rejects_hardcoded_cni_tag(checker):
    checker.CNI_BIN.write_text(
        GOOD_CNI.replace("%{cni-upstream-tag}", "v1.9.1"), encoding="utf-8"
    )
    assert "hardcodes the upstream CNI" in _run(checker)


# --- main(): sysext asset filename ---------------------------------------


def test_main_rejects_missing_fname(checker):
    checker.K8S_SYSEXT.write_text(
        GOOD_SYSEXT.replace('FNAME="kubernetes-%{k8s-version}.raw"', ""),
        encoding="utf-8",
    )
    assert 'declares no FNAME="..." asset name' in _run(checker)


def test_main_rejects_fname_on_the_os_release_axis(checker):
    checker.K8S_SYSEXT.write_text(
        GOOD_SYSEXT.replace("%{k8s-version}.raw", "%{release-version}.raw", 1),
        encoding="utf-8",
    )
    assert "names the Kubernetes sysext on the\n  OS release axis" in _run(checker)


def test_main_rejects_fname_not_derived_from_k8s_version(checker):
    checker.K8S_SYSEXT.write_text(
        GOOD_SYSEXT.replace(
            'FNAME="kubernetes-%{k8s-version}.raw"', 'FNAME="kubernetes.raw"'
        ),
        encoding="utf-8",
    )
    assert "does not derive the sysext asset\n  name" in _run(checker)


def test_main_rejects_missing_generated_version_id(checker):
    checker.K8S_SYSEXT.write_text(
        GOOD_SYSEXT.replace(
            'echo "VERSION_ID=%{k8s-version}" >> extension-release.kubernetes', ""
        ),
        encoding="utf-8",
    )
    assert "does not generate VERSION_ID= from" in _run(checker)


# --- main(): /usr/local/share version stamps -----------------------------


@pytest.mark.parametrize(
    "stamp", ["kubernetes-version", "kubernetes-cni-version"]
)
def test_main_rejects_a_missing_version_stamp(checker, stamp):
    checker.K8S_SYSEXT.write_text(
        "\n".join(
            line
            for line in GOOD_SYSEXT.splitlines()
            if not line.strip().endswith(f"sysext/usr/local/share/{stamp}")
        )
        + "\n",
        encoding="utf-8",
    )
    message = _run(checker)
    assert "does not generate" in message
    assert f"/usr/local/share/{stamp}" in message


def test_main_rejects_cni_stamp_written_from_the_kubernetes_atom(checker):
    checker.K8S_SYSEXT.write_text(
        GOOD_SYSEXT.replace(
            'echo "%{cni-version}" > sysext/usr/local/share/kubernetes-cni-version',
            'echo "%{k8s-version}" > sysext/usr/local/share/kubernetes-cni-version',
        ),
        encoding="utf-8",
    )
    assert "/usr/local/share/kubernetes-cni-version" in _run(checker)


# --- main(): extension-release.kubernetes --------------------------------


def test_main_rejects_hardcoded_version_id_in_extension_release(checker):
    checker.EXTENSION_RELEASE.write_text(
        "NAME=kubernetes\nID=_any\nVERSION_ID=1.36.4\n", encoding="utf-8"
    )
    message = _run(checker)
    assert "hardcodes a\n  version" in message
    assert "VERSION_ID=1.36.4" in message


def test_main_rejects_indented_hardcoded_version_id(checker):
    checker.EXTENSION_RELEASE.write_text(
        "NAME=kubernetes\n  VERSION_ID=9.9.9\n", encoding="utf-8"
    )
    assert "hardcodes a\n  version" in _run(checker)


# --- main(): literal version scan ----------------------------------------


@pytest.mark.parametrize(
    "attr",
    ["K8S_BIN", "CNI_BIN", "K8S_SYSEXT", "EXTENSION_RELEASE"],
)
def test_main_rejects_literal_version_in_any_consumer(checker, attr):
    path = getattr(checker, attr)
    path.write_text(
        path.read_text(encoding="utf-8") + "\nnote: shipped v1.36.4\n",
        encoding="utf-8",
    )
    message = _run(checker)
    assert "restates a literal Kubernetes or CNI" in message
    assert "Literal: v1.36.4" in message


# --- main(): sysupdate MatchPattern --------------------------------------


def test_main_rejects_missing_match_pattern(checker):
    checker.TRANSFER.write_text("[Source]\nType=url-file\n", encoding="utf-8")
    assert "declares no\n  [Source]" in _run(checker)


def test_main_rejects_match_pattern_without_zst_suffix(checker):
    checker.TRANSFER.write_text(
        "[Source]\nMatchPattern=kubernetes-@v.raw\n", encoding="utf-8"
    )
    assert "declares no\n  [Source]" in _run(checker)


def test_main_rejects_prefix_drift_between_fname_and_match_pattern(checker):
    checker.TRANSFER.write_text(
        "[Source]\nMatchPattern=k8s-@v.raw.zst\n", encoding="utf-8"
    )
    message = _run(checker)
    assert "is not the pinned Kubernetes version" in message
    assert "'@v' captures  : None" in message


def test_main_rejects_suffix_drift_between_fname_and_match_pattern(checker):
    checker.K8S_SYSEXT.write_text(
        GOOD_SYSEXT.replace(
            'FNAME="kubernetes-%{k8s-version}.raw"',
            'FNAME="kubernetes-%{k8s-version}.erofs"',
        ),
        encoding="utf-8",
    )
    assert "is not the pinned Kubernetes version" in _run(checker)


def test_main_rejects_match_pattern_that_captures_extra_text(checker):
    checker.TRANSFER.write_text(
        "[Source]\nMatchPattern=kuber@v.raw.zst\n", encoding="utf-8"
    )
    message = _run(checker)
    assert "is not the pinned Kubernetes version" in message
    assert f"'@v' captures  : 'netes-{EXPECTED_VERSION}'" in message
