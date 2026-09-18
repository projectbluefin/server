"""Unit coverage for .github/scripts/check-flatcar-version.py.

The script enforces that include/flatcar.yml is the single source of truth for
every Flatcar upstream pin (version, kernel vermagic, source sha256): no pin
may be hardcoded in elements/ or files/. When it regresses, a pin can drift
from the pin file and silently pull a different upstream payload, so every
branch of declared_pins(), iter_scan_files() and main() is exercised here.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "check-flatcar-version.py"

PIN_FILE_TEXT = (
    "variables:\n"
    '  flatcar-version: "4593.2.5"\n'
    '  flatcar-kver: "6.12.102-flatcar"\n'
    "  flatcar-zfs-sha256: "
    '"bed24d0a31b6c9ff0f1d59ec2b50d25585bf9bbcb8e9e96f5706f1a17948d971"\n'
)


def _load_module():
    spec = importlib.util.spec_from_file_location("check_flatcar_version", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_flatcar_version"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def checker(tmp_path):
    """Fresh module instance rooted at tmp_path with a synthetic pin file."""
    module = _load_module()
    module.ROOT = tmp_path
    (tmp_path / "include").mkdir()
    (tmp_path / "include" / "flatcar.yml").write_text(PIN_FILE_TEXT, encoding="utf-8")
    module.PIN_FILE = tmp_path / "include" / "flatcar.yml"
    (tmp_path / "elements").mkdir()
    (tmp_path / "files").mkdir()
    module.SCAN_DIRS = (tmp_path / "elements", tmp_path / "files")
    yield module
    sys.modules.pop("check_flatcar_version", None)


# --- declared_pins --------------------------------------------------------


def test_declared_pins_extracts_versions_and_sha256(checker):
    pins = checker.declared_pins(PIN_FILE_TEXT)
    assert pins == [
        "4593.2.5",
        "6.12.102-flatcar",
        "bed24d0a31b6c9ff0f1d59ec2b50d25585bf9bbcb8e9e96f5706f1a17948d971",
    ]


def test_declared_pins_handles_bare_and_single_quoted_values():
    text = (
        "variables:\n"
        "  bare: 1.2.3\n"
        "  single: '4.5.6'\n"
    )
    module = _load_module()
    try:
        assert module.declared_pins(text) == ["1.2.3", "4.5.6"]
    finally:
        sys.modules.pop("check_flatcar_version", None)


def test_declared_pins_ignores_comments_and_headers():
    text = (
        "# single source of truth\n"
        "variables:\n"
        "  flatcar-version: \"4593.2.5\"  # the release\n"
    )
    module = _load_module()
    try:
        assert module.declared_pins(text) == ["4593.2.5"]
    finally:
        sys.modules.pop("check_flatcar_version", None)


# --- read / missing pin file ---------------------------------------------


def test_read_exits_on_missing_pin_file(checker):
    checker.PIN_FILE = checker.PIN_FILE.parent / "missing.yml"
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    assert "expected file not found" in str(excinfo.value)


def test_main_exits_when_no_pins_declared(tmp_path):
    (tmp_path / "include").mkdir(parents=True)
    (tmp_path / "include" / "flatcar.yml").write_text("variables:\n", encoding="utf-8")
    module = _load_module()
    module.ROOT = tmp_path
    module.PIN_FILE = tmp_path / "include" / "flatcar.yml"
    module.SCAN_DIRS = ()
    try:
        with pytest.raises(SystemExit) as excinfo:
            module.main()
        assert "declares no pins" in str(excinfo.value)
    finally:
        sys.modules.pop("check_flatcar_version", None)


# --- main() ---------------------------------------------------------------


def test_main_passes_when_tree_is_clean(checker):
    (checker.ROOT / "elements" / "flatcar-zfs.bst").write_text(
        "sources:\n"
        "  - kind: remote\n"
        "    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-zfs.raw\n"
        "    ref: %{flatcar-zfs-sha256}\n",
        encoding="utf-8",
    )
    checker.main()


def test_main_fails_when_sha256_hardcoded_in_element(checker, capsys):
    (checker.ROOT / "elements" / "flatcar-zfs.bst").write_text(
        "sources:\n"
        "  - kind: remote\n"
        "    url: flatcar:stable/%{flatcar-board}/%{flatcar-version}/flatcar-zfs.raw\n"
        "    ref: bed24d0a31b6c9ff0f1d59ec2b50d25585bf9bbcb8e9e96f5706f1a17948d971\n",
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    message = str(excinfo.value)
    assert "hardcoded outside" in message
    assert "flatcar-zfs.bst" in message
    assert "bed24d0a31b6c9ff0f1d59ec2b50d25585bf9bbcb8e9e96f5706f1a17948d971" in message


def test_main_fails_when_version_hardcoded_in_files(checker, capsys):
    (checker.ROOT / "files" / "os-release").write_text(
        'NAME="Bluefin Server"\nVERSION="4593.2.5-fsd"\n', encoding="utf-8"
    )
    with pytest.raises(SystemExit) as excinfo:
        checker.main()
    message = str(excinfo.value)
    assert "hardcoded outside" in message
    assert "files/os-release" in message
    assert "4593.2.5" in message


def test_main_skips_binary_and_scanned_hidden_dirs(checker):
    # A sha256 inside a .git / __pycache__ dir must NOT be flagged.
    git_dir = checker.ROOT / "elements" / ".git"
    pycache = checker.ROOT / "elements" / "__pycache__"
    git_dir.mkdir(parents=True)
    pycache.mkdir(parents=True)
    (git_dir / "keep").write_text(
        "bed24d0a31b6c9ff0f1d59ec2b50d25585bf9bbcb8e9e96f5706f1a17948d971\n",
        encoding="utf-8",
    )
    (pycache / "x.pyc").write_bytes(b"\x00bed24d0a31b6c9ff0f1d59ec2b50d25585\n")
    checker.main()


# --- live repository invariant -------------------------------------------


def test_real_repository_has_no_hardcoded_flatcar_pins(capsys):
    """The checked-in tree must satisfy the invariant the script enforces."""
    module = _load_module()
    try:
        module.main()
    finally:
        sys.modules.pop("check_flatcar_version", None)
    assert "OK: no Flatcar pins" in capsys.readouterr().out
