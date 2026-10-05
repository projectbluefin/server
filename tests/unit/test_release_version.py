"""Unit coverage for .github/scripts/check-release-version.py.

The script is the gate protecting against drift between ``installer-version``
in ``project.conf`` and the FSDK point release pinned in
``elements/freedesktop-sdk.bst``. Every
branch of ``read()``, ``main()`` and all module-level regexes is exercised here.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check-release-version.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("check_release_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_release_version"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path):
    """Fresh module instance with its path constants rooted at tmp_path.

    ``ROOT``/``PROJECT_CONF``/``FSDK_JUNCTION`` are module-level
    globals derived from the script's own location, so each test gets a
    re-imported copy pointed at an isolated tree.
    """
    module = _load_module()
    module.ROOT = tmp_path
    module.PROJECT_CONF = tmp_path / "project.conf"
    module.FSDK_JUNCTION = tmp_path / "elements" / "freedesktop-sdk.bst"
    module.FSDK_JUNCTION.parent.mkdir(parents=True, exist_ok=True)
    yield module
    sys.modules.pop("check_release_version", None)


def _write(
    checker,
    installer_declared="26.08.0",
    fsdk_pinned="26.08.0",
):
    checker.PROJECT_CONF.write_text(
        f'variables:\n  installer-version: "{installer_declared}"\n',
        encoding="utf-8",
    )
    checker.FSDK_JUNCTION.write_text(
        f"junction:\n  ref: freedesktop-sdk-{fsdk_pinned}-0-gdb97cce\n",
        encoding="utf-8",
    )


# --- read() ---------------------------------------------------------------


def test_read_returns_file_contents(checker, tmp_path):
    target = tmp_path / "project.conf"
    target.write_text("hello\n", encoding="utf-8")
    assert checker.read(target) == "hello\n"


def test_read_exits_on_missing_file(checker, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        checker.read(tmp_path / "project.conf")
    assert "expected file not found" in str(excinfo.value)
    assert "project.conf" in str(excinfo.value)


def test_read_exits_when_path_is_a_directory(checker, tmp_path):
    with pytest.raises(SystemExit) as excinfo:
        checker.read(tmp_path / "elements")
    assert "expected file not found" in str(excinfo.value)


# --- INSTALLER_VERSION_RE -------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        '  installer-version: "26.08.0"',
        "  installer-version: '26.08.0'",
        "  installer-version: 26.08.0",
        "installer-version: 26.08.0",
        "\tinstaller-version: 26.08.0",
        '  installer-version: "26.08.0"  ',
    ],
)
def test_installer_version_re_accepts_supported_spellings(checker, line):
    match = checker.INSTALLER_VERSION_RE.search(f"variables:\n{line}\n")
    assert match is not None
    assert match.group(1) == "26.08.0"


@pytest.mark.parametrize(
    "line",
    [
        "  installer-version: 26.08",
        "  installer-version:",
        "  other-installer-version-thing: 1.2.3",
        "  # installer-version: 1.2.3",
    ],
)
def test_installer_version_re_rejects_malformed_declarations(checker, line):
    assert checker.INSTALLER_VERSION_RE.search(f"variables:\n{line}\n") is None


# --- FSDK_REF_RE ----------------------------------------------------------


def test_fsdk_ref_re_extracts_point_release_from_ref(checker):
    match = checker.FSDK_REF_RE.search(
        "  ref: freedesktop-sdk-26.08.0-0-gdb97cce32cecadc7a3e98f06d557ebfa6ba9ad46\n"
    )
    assert match.group(1) == "26.08.0"


def test_fsdk_ref_re_ignores_two_component_track_glob(checker):
    assert checker.FSDK_REF_RE.search("  track: freedesktop-sdk-26.08*\n") is None



# --- main() ---------------------------------------------------------------


def test_main_passes_when_versions_match(checker, capsys):
    _write(
        checker,
        installer_declared="26.08.0",
        fsdk_pinned="26.08.0",
    )
    checker.main()
    out = capsys.readouterr().out
    assert "OK: installer-version 26.08.0" in out


def test_main_exits_when_project_conf_missing(checker):
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "expected file not found" in str(excinfo.value)


def test_main_exits_when_junction_missing(checker):
    checker.PROJECT_CONF.write_text(
        'variables:\n  installer-version: "26.08.0"\n',
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "expected file not found" in str(excinfo.value)



def test_main_exits_when_installer_version_not_declared(checker):
    checker.PROJECT_CONF.write_text("variables:\n  other: 1\n", encoding="utf-8")
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "does not declare an 'installer-version" in str(excinfo.value)


def test_main_exits_when_junction_has_no_point_release(checker):
    checker.PROJECT_CONF.write_text(
        'variables:\n  installer-version: "26.08.0"\n',
        encoding="utf-8",
    )
    checker.FSDK_JUNCTION.write_text(
        "junction:\n  track: freedesktop-sdk-26.08*\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "no 'freedesktop-sdk-X.Y.Z' point release" in str(excinfo.value)



def test_main_exits_on_installer_drift_and_names_both_versions(checker):
    _write(checker, installer_declared="26.08.0", fsdk_pinned="26.08.1")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    message = str(excinfo.value)
    assert "installer-version drift" in message
    assert "26.08.0" in message
    assert "26.08.1" in message
    assert 'set installer-version to "26.08.1"' in message


def test_main_installer_drift_is_detected_across_minor_lines(checker):
    _write(checker, installer_declared="25.08.0", fsdk_pinned="26.08.0")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "installer-version drift" in str(excinfo.value)


# --- --print-fsdk / --fix ---------------------------------------------------


def test_print_fsdk_prints_only_the_pinned_point_release(checker, capsys):
    _write(checker, installer_declared="25.08.0", fsdk_pinned="26.08.3")
    checker.main(["--print-fsdk"])
    assert capsys.readouterr().out == "26.08.3\n"


def test_print_fsdk_fails_without_a_point_release(checker):
    checker.FSDK_JUNCTION.write_text("junction:\n  track: freedesktop-sdk-26.08*\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main(["--print-fsdk"])
    assert "no 'freedesktop-sdk-X.Y.Z' point release" in str(excinfo.value)


@pytest.mark.parametrize("declared", ['"26.08.0"', "26.08.0", "'25.08.9'", '"garbage"', ""])
def test_fix_syncs_installer_version_and_keeps_the_rest(checker, capsys, declared):
    checker.PROJECT_CONF.write_text(
        f"# installer-version: 1.2.3\nvariables:\n  installer-version: {declared}\n  other: x\n",
        encoding="utf-8",
    )
    checker.FSDK_JUNCTION.write_text("  ref: freedesktop-sdk-26.08.1-0-gdb97cce\n", encoding="utf-8")
    checker.main(["--fix"])
    assert checker.PROJECT_CONF.read_text(encoding="utf-8") == (
        '# installer-version: 1.2.3\nvariables:\n  installer-version: "26.08.1"\n  other: x\n'
    )
    assert "OK: installer-version 26.08.1" in capsys.readouterr().out


def test_fix_still_fails_when_installer_version_is_not_declared(checker):
    checker.PROJECT_CONF.write_text("variables:\n  other: 1\n", encoding="utf-8")
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main(["--fix"])
    assert "does not declare an 'installer-version" in str(excinfo.value)


def test_fix_and_print_fsdk_are_exclusive(checker):
    _write(checker)
    with pytest.raises(SystemExit):
        checker.main(["--fix", "--print-fsdk"])


def test_callers_use_the_script_instead_of_parsing_the_junction():
    """One parser of the FSDK point release: the Justfile and track-junctions call it."""
    justfile = (REPO_ROOT / "Justfile").read_text(encoding="utf-8")
    fsdk_version = next(line for line in justfile.splitlines() if line.startswith("export fsdk_version"))
    assert "check-release-version.py --print-fsdk" in fsdk_version
    tracker = (REPO_ROOT / ".github" / "workflows" / "track-junctions.yml").read_text(encoding="utf-8")
    assert "check-release-version.py --fix" in tracker
    for text in (justfile, tracker):
        assert "freedesktop-sdk-[0-9]" not in text


# --- live repository invariant -------------------------------------------


def test_real_repository_has_no_release_version_drift(capsys):
    """The checked-in tree must satisfy the invariant the script enforces."""
    module = _load_module()
    try:
        module.main()
    finally:
        sys.modules.pop("check_release_version", None)
    out = capsys.readouterr().out
    assert "OK: installer-version" in out
