"""Unit coverage for .github/scripts/check-k0s-version.py.

The script is the only gate holding the k0s version axis together. It is run by
``just validate`` and by the ``check-k0s-version`` pre-commit hook, but before
this module it had no direct test: ``tests/unit/test_k0s_version.py`` only
asserts the *repository's current* file contents and never executes the script,
so every fail-closed branch could regress to fail-open unnoticed.

Covered here: ``read()``, ``scalar()``, ``expand()``, ``fail()`` and each
rejection path of ``main()`` — non-filename-safe version, missing/hardcoded
upstream URL, missing/OS-axis/underived ``FNAME``, missing generated
``VERSION_ID``, a hardcoded ``VERSION_ID=`` in extension-release.k0s, literal
k0s versions restated in any consumer, a missing sysupdate ``MatchPattern``,
and an asset name whose ``@v`` capture disagrees with ``%{k0s-version}``.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check-k0s-version.py"

GOOD_INCLUDE = """variables:
  k0s-k8s-version: "1.36.4"
  k0s-patch: "0"

  k0s-upstream-tag: "v%{k0s-k8s-version}%2Bk0s.%{k0s-patch}"
  k0s-version: "%{k0s-k8s-version}-k0s.%{k0s-patch}"
"""

GOOD_BIN = """kind: manual
sources:
  - kind: remote
    url: github:k0sproject/k0s/releases/download/%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-amd64
    ref: ca1e9e68107335846e8296777fce2ccd654284e6265b4b5d32c34ead872af98f
"""

GOOD_SYSEXT = """kind: manual
config:
  install-commands:
    - |
      FNAME="k0s-%{k0s-version}.raw"
      echo "VERSION_ID=%{k0s-version}" >> extension-release.k0s
"""

GOOD_EXTENSION_RELEASE = "NAME=k0s\nID=_any\n"

GOOD_TRANSFER = """[Source]
Type=url-file
MatchPattern=k0s-@v.raw.zst

[Target]
MatchPattern=k0s-@v.raw
"""

EXPECTED_VERSION = "1.36.4-k0s.0"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_k0s_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_k0s_version"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path):
    """Fresh module instance with its path constants rooted at tmp_path.

    ``ROOT`` and the five consumer paths are module-level globals derived from
    the script's own location, so each test gets a re-imported copy repointed at
    an isolated tree pre-populated with a passing configuration.
    """
    module = _load_module()
    module.ROOT = tmp_path
    module.K0S_INCLUDE = tmp_path / "include" / "k0s.yml"
    module.K0S_BIN = tmp_path / "elements" / "k0s" / "k0s-bin.bst"
    module.K0S_SYSEXT = tmp_path / "elements" / "oci" / "k0s-sysext.bst"
    module.EXTENSION_RELEASE = (
        tmp_path / "files" / "k0s" / "sysext" / "extension-release.k0s"
    )
    module.TRANSFER = tmp_path / "files" / "os" / "sysupdate.d" / "70-k0s.transfer"
    for path, text in (
        (module.K0S_INCLUDE, GOOD_INCLUDE),
        (module.K0S_BIN, GOOD_BIN),
        (module.K0S_SYSEXT, GOOD_SYSEXT),
        (module.EXTENSION_RELEASE, GOOD_EXTENSION_RELEASE),
        (module.TRANSFER, GOOD_TRANSFER),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    yield module
    sys.modules.pop("check_k0s_version", None)


def _run(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    return str(excinfo.value)


# --- read() ---------------------------------------------------------------


def test_read_returns_file_contents(checker, tmp_path):
    target = tmp_path / "include" / "k0s.yml"
    assert checker.read(target) == GOOD_INCLUDE


def test_read_exits_on_missing_file(checker, tmp_path):
    missing = tmp_path / "include" / "gone.yml"
    with pytest.raises(SystemExit) as excinfo:
        checker.read(missing)
    assert "expected file not found" in str(excinfo.value)
    assert "include/gone.yml" in str(excinfo.value)


# --- scalar() -------------------------------------------------------------


def test_scalar_reads_double_quoted_value(checker):
    assert checker.scalar(GOOD_INCLUDE, "k0s-patch", "where") == "0"


def test_scalar_reads_single_quoted_value(checker):
    text = "variables:\n  k0s-patch: '3'\n"
    assert checker.scalar(text, "k0s-patch", "where") == "3"


def test_scalar_ignores_unquoted_value(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.scalar("variables:\n  k0s-patch: 0\n", "k0s-patch", "include/k0s.yml")
    assert "does not declare a 'k0s-patch:' variable" in str(excinfo.value)


def test_scalar_exits_when_name_absent(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.scalar(GOOD_INCLUDE, "k0s-nope", "include/k0s.yml")
    assert "include/k0s.yml does not declare a 'k0s-nope:' variable" in str(
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
        checker.expand("%{missing}", {}, "include/k0s.yml x")
    assert "references undefined variable '%{missing}'" in str(excinfo.value)


def test_expand_exits_on_circular_reference(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.expand("%{a}", {"a": "%{b}", "b": "%{a}"}, "include/k0s.yml x")
    assert "circular variable reference" in str(excinfo.value)


# --- fail() ---------------------------------------------------------------


def test_fail_reports_problem_and_fix(checker):
    with pytest.raises(SystemExit) as excinfo:
        checker.fail("something drifted", "do the thing")
    message = str(excinfo.value)
    assert "ERROR: something drifted" in message
    assert "Fix: do the thing" in message


# --- module-level regexes -------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    ["1.36.4-k0s.0", "v1.36.4", "1.36.4+k0s.0", "release~1^2"],
)
def test_safe_version_re_accepts_filename_safe_versions(checker, candidate):
    assert checker.SAFE_VERSION_RE.match(candidate)


@pytest.mark.parametrize("candidate", ["1.36.4 k0s", "1.36.4/0", "", "a:b"])
def test_safe_version_re_rejects_unsafe_versions(checker, candidate):
    assert not checker.SAFE_VERSION_RE.match(candidate)


@pytest.mark.parametrize(
    "candidate",
    ["v1.36.4+k0s.0", "1.36.4%2Bk0s.0", "1.36.4-k0s.12"],
)
def test_literal_version_re_matches_every_spelling(checker, candidate):
    assert checker.LITERAL_VERSION_RE.search(candidate)


def test_literal_version_re_ignores_templated_reference(checker):
    assert not checker.LITERAL_VERSION_RE.search("%{k0s-upstream-tag}")


# --- main(): the passing path --------------------------------------------


def test_main_accepts_a_fully_derived_configuration(checker, capsys):
    checker.main()
    out = capsys.readouterr().out
    assert "OK: k0s v1.36.4%2Bk0s.0 pinned in include/k0s.yml" in out
    assert f"asset k0s-{EXPECTED_VERSION}.raw.zst" in out
    assert f"VERSION_ID={EXPECTED_VERSION}" in out


def test_main_tolerates_literal_version_inside_comments(checker, capsys):
    checker.K0S_BIN.write_text(
        "# pinned from the v1.36.4+k0s.0 release notes\n" + GOOD_BIN,
        encoding="utf-8",
    )
    checker.main()
    assert "OK: k0s" in capsys.readouterr().out


# --- main(): version safety ----------------------------------------------


def test_main_rejects_version_that_is_not_filename_safe(checker):
    checker.K0S_INCLUDE.write_text(
        GOOD_INCLUDE.replace('k0s-patch: "0"', 'k0s-patch: "0 rc1"'),
        encoding="utf-8",
    )
    assert "is not filename-safe" in _run(checker)


# --- main(): upstream download URL ---------------------------------------


def test_main_rejects_missing_source_url(checker):
    checker.K0S_BIN.write_text("kind: manual\nsources: []\n", encoding="utf-8")
    assert "declares no source 'url:'" in _run(checker)


def test_main_rejects_hardcoded_upstream_tag_in_url(checker):
    checker.K0S_BIN.write_text(
        "sources:\n"
        "  - kind: remote\n"
        "    url: github:k0sproject/k0s/releases/download/v1.36.4%2Bk0s.0/k0s-amd64\n",
        encoding="utf-8",
    )
    assert "hardcodes the upstream k0s release tag" in _run(checker)


# --- main(): sysext asset filename ---------------------------------------


def test_main_rejects_missing_fname(checker):
    checker.K0S_SYSEXT.write_text(
        'echo "VERSION_ID=%{k0s-version}"\n', encoding="utf-8"
    )
    assert 'declares no FNAME="..." asset name' in _run(checker)


def test_main_rejects_fname_on_the_os_release_axis(checker):
    checker.K0S_SYSEXT.write_text(
        GOOD_SYSEXT.replace("%{k0s-version}.raw", "%{release-version}.raw", 1),
        encoding="utf-8",
    )
    assert "names the k0s sysext on the OS release" in _run(checker)


def test_main_rejects_fname_not_derived_from_k0s_version(checker):
    checker.K0S_SYSEXT.write_text(
        GOOD_SYSEXT.replace('FNAME="k0s-%{k0s-version}.raw"', 'FNAME="k0s.raw"'),
        encoding="utf-8",
    )
    assert "does not derive the sysext asset name" in _run(checker)


def test_main_rejects_missing_generated_version_id(checker):
    checker.K0S_SYSEXT.write_text(
        'FNAME="k0s-%{k0s-version}.raw"\n', encoding="utf-8"
    )
    assert "does not generate VERSION_ID= from" in _run(checker)


# --- main(): extension-release.k0s ---------------------------------------


def test_main_rejects_hardcoded_version_id_in_extension_release(checker):
    checker.EXTENSION_RELEASE.write_text(
        "NAME=k0s\nID=_any\nVERSION_ID=1.36.4-k0s.0\n", encoding="utf-8"
    )
    message = _run(checker)
    assert "hardcodes a version" in message
    assert "VERSION_ID=1.36.4-k0s.0" in message


def test_main_rejects_indented_hardcoded_version_id(checker):
    checker.EXTENSION_RELEASE.write_text(
        "NAME=k0s\n  VERSION_ID=9.9.9\n", encoding="utf-8"
    )
    assert "hardcodes a version" in _run(checker)


# --- main(): literal version scan ----------------------------------------


@pytest.mark.parametrize(
    "attr",
    ["K0S_BIN", "K0S_SYSEXT", "EXTENSION_RELEASE"],
)
def test_main_rejects_literal_version_in_any_consumer(checker, attr):
    path = getattr(checker, attr)
    path.write_text(
        path.read_text(encoding="utf-8") + "\nnote: shipped v1.36.4+k0s.0\n",
        encoding="utf-8",
    )
    message = _run(checker)
    assert "restates a literal k0s version" in message
    assert "Literal: v1.36.4+k0s.0" in message


# --- main(): sysupdate MatchPattern --------------------------------------


def test_main_rejects_missing_match_pattern(checker):
    checker.TRANSFER.write_text("[Source]\nType=url-file\n", encoding="utf-8")
    assert "declares no [Source]" in _run(checker)


def test_main_rejects_match_pattern_without_zst_suffix(checker):
    checker.TRANSFER.write_text(
        "[Source]\nMatchPattern=k0s-@v.raw\n", encoding="utf-8"
    )
    assert "declares no [Source]" in _run(checker)


def test_main_rejects_prefix_drift_between_fname_and_match_pattern(checker):
    checker.TRANSFER.write_text(
        "[Source]\nMatchPattern=kzeros-@v.raw.zst\n", encoding="utf-8"
    )
    message = _run(checker)
    assert "is not the pinned k0s version" in message
    assert "'@v' captures  : None" in message


def test_main_rejects_suffix_drift_between_fname_and_match_pattern(checker):
    checker.K0S_SYSEXT.write_text(
        GOOD_SYSEXT.replace(
            'FNAME="k0s-%{k0s-version}.raw"', 'FNAME="k0s-%{k0s-version}.erofs"'
        ),
        encoding="utf-8",
    )
    assert "is not the pinned k0s version" in _run(checker)


def test_main_rejects_match_pattern_that_captures_extra_text(checker):
    checker.TRANSFER.write_text(
        "[Source]\nMatchPattern=k@v.raw.zst\n", encoding="utf-8"
    )
    message = _run(checker)
    assert "is not the pinned k0s version" in message
    assert f"'@v' captures  : '0s-{EXPECTED_VERSION}'" in message
