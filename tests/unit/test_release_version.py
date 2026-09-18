"""Unit coverage for .github/scripts/check-release-version.py.

The script is the gate protecting against version drift on the two release
axes: the installer axis declared in ``project.conf`` and pinned in
``elements/freedesktop-sdk.bst``, and the Flatcar OS payload axis declared in
``include/flatcar.yml``.

When either regresses, CI publishes release assets carrying stale version
strings and systemd-sysupdate or operators see version mismatches, so every
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

    ``ROOT``/``PROJECT_CONF``/``FSDK_JUNCTION``/``FLATCAR_PIN`` are module-level
    globals derived from the script's own location, so each test gets a
    re-imported copy pointed at an isolated tree.
    """
    module = _load_module()
    module.ROOT = tmp_path
    module.PROJECT_CONF = tmp_path / "project.conf"
    module.FSDK_JUNCTION = tmp_path / "elements" / "freedesktop-sdk.bst"
    module.FLATCAR_PIN = tmp_path / "include" / "flatcar.yml"
    module.FSDK_JUNCTION.parent.mkdir(parents=True, exist_ok=True)
    module.FLATCAR_PIN.parent.mkdir(parents=True, exist_ok=True)
    yield module
    sys.modules.pop("check_release_version", None)


def _write(
    checker,
    installer_declared="26.08.0",
    fsdk_pinned="26.08.0",
    flatcar_pinned="4593.2.5",
):
    checker.PROJECT_CONF.write_text(
        f'variables:\n  installer-version: "{installer_declared}"\n',
        encoding="utf-8",
    )
    checker.FSDK_JUNCTION.write_text(
        f"junction:\n  ref: freedesktop-sdk-{fsdk_pinned}-0-gdb97cce\n",
        encoding="utf-8",
    )
    checker.FLATCAR_PIN.write_text(
        "variables:\n"
        f'  flatcar-version: "{flatcar_pinned}"\n'
        '  flatcar-kver: "6.12.102-flatcar"\n',
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


# --- FLATCAR_PIN_RE -------------------------------------------------------


def test_flatcar_pin_re_extracts_version_from_pin(checker):
    match = checker.FLATCAR_PIN_RE.search('  flatcar-version: "4593.2.5"\n')
    assert match.group(1) == "4593.2.5"


def test_flatcar_pin_re_rejects_malformed(checker):
    assert checker.FLATCAR_PIN_RE.search("  flatcar-version: 4593.2\n") is None


# --- main() ---------------------------------------------------------------


def test_main_passes_when_versions_match(checker, capsys):
    _write(
        checker,
        installer_declared="26.08.0",
        fsdk_pinned="26.08.0",
        flatcar_pinned="4593.2.5",
    )
    checker.main()
    out = capsys.readouterr().out
    assert "OK: installer-version 26.08.0" in out
    assert "OK: flatcar-version 4593.2.5" in out


def test_main_exits_when_project_conf_missing(checker):
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    checker.FLATCAR_PIN.write_text('flatcar-version: "4593.2.5"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "expected file not found" in str(excinfo.value)


def test_main_exits_when_junction_missing(checker):
    checker.PROJECT_CONF.write_text(
        'variables:\n  installer-version: "26.08.0"\n',
        encoding="utf-8",
    )
    checker.FLATCAR_PIN.write_text('flatcar-version: "4593.2.5"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "expected file not found" in str(excinfo.value)


def test_main_exits_when_flatcar_pin_missing(checker):
    checker.PROJECT_CONF.write_text(
        'variables:\n  installer-version: "26.08.0"\n',
        encoding="utf-8",
    )
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "expected file not found" in str(excinfo.value)


def test_main_exits_when_installer_version_not_declared(checker):
    checker.PROJECT_CONF.write_text("variables:\n  other: 1\n", encoding="utf-8")
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    checker.FLATCAR_PIN.write_text('flatcar-version: "4593.2.5"\n', encoding="utf-8")
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
    checker.FLATCAR_PIN.write_text('flatcar-version: "4593.2.5"\n', encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "no 'freedesktop-sdk-X.Y.Z' point release" in str(excinfo.value)


def test_main_exits_when_flatcar_pin_has_no_version(checker):
    checker.PROJECT_CONF.write_text(
        'variables:\n  installer-version: "26.08.0"\n',
        encoding="utf-8",
    )
    checker.FSDK_JUNCTION.write_text("ref: freedesktop-sdk-26.08.0\n", encoding="utf-8")
    checker.FLATCAR_PIN.write_text("variables:\n  other: 1\n", encoding="utf-8")
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "does not declare a 'flatcar-version: X.Y.Z'" in str(excinfo.value)


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
    assert "OK: flatcar-version" in out
