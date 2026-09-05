"""Unit tests for .github/scripts/verify-release.py."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".github/scripts/verify-release.py"
spec = importlib.util.spec_from_file_location("verify_release", SCRIPT)
verify_release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_release)

VERSION = "24.08.3"
EXPECTED = {pattern.format(version=VERSION) for pattern in verify_release.ARTIFACT_PATTERNS}


def run(monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["verify-release.py", *argv])
    return verify_release.main()


def populate(directory: Path, names) -> None:
    for name in names:
        (directory / name).touch()


def test_complete_artifact_set_passes(tmp_path, monkeypatch):
    populate(tmp_path, EXPECTED)
    assert run(monkeypatch, "--version", VERSION, "--directory", str(tmp_path)) == 0


def test_missing_artifact_fails(tmp_path, monkeypatch, capsys):
    populate(tmp_path, sorted(EXPECTED)[1:])
    assert run(monkeypatch, "--version", VERSION, "--directory", str(tmp_path)) == 1
    assert "missing release artifacts" in capsys.readouterr().err


def test_unexpected_artifact_fails(tmp_path, monkeypatch, capsys):
    populate(tmp_path, EXPECTED | {"stale-0.0.0.raw.zst"})
    assert run(monkeypatch, "--version", VERSION, "--directory", str(tmp_path)) == 1
    assert "unexpected release artifacts" in capsys.readouterr().err


def test_missing_directory_fails(tmp_path, monkeypatch, capsys):
    assert run(monkeypatch, "--version", VERSION, "--directory", str(tmp_path / "nope")) == 1
    assert "does not exist" in capsys.readouterr().err


def test_invalid_version_rejected(monkeypatch):
    with pytest.raises(SystemExit):
        run(monkeypatch, "--version", "v1.2", "--directory", ".")
