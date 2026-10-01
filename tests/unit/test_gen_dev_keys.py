"""scripts/gen-dev-keys.sh never replaces existing keys without --force.

Each case runs a copy of the script against a scratch files/boot-keys/ with
openssl and gpg replaced by stubs that log their calls, so no key material is
generated and a refusal can be told apart from a regeneration.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "gen-dev-keys.sh"

SIGNING = ["sysupdate-signing.asc", "import-pubring.pgp"]
BOOT = [
    "PK.key",
    "PK.crt",
    "KEK.key",
    "KEK.crt",
    "DB.key",
    "DB.crt",
    "linux-module-cert.key",
    "modules/linux-module-cert.crt",
]


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts" / SCRIPT.name)
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    for tool in ("openssl", "gpg"):
        stub = stubs / tool
        stub.write_text(f'#!/bin/sh\necho {tool} >> "$STUB_LOG"\nexit 1\n')
        stub.chmod(0o755)
    return tmp_path


def seed(tree: Path, names: list[str]) -> None:
    keys = tree / "files" / "boot-keys"
    for name in names:
        path = keys / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"existing {name}\n")


def snapshot(tree: Path) -> dict[str, str]:
    keys = tree / "files" / "boot-keys"
    return {
        str(p.relative_to(keys)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(keys.rglob("*"))
        if p.is_file()
    }


def run(tree: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PATH"] = f"{tree / 'stubs'}:{env['PATH']}"
    env["STUB_LOG"] = str(tree / "stub.log")
    return subprocess.run(
        ["bash", str(tree / "scripts" / SCRIPT.name), *args],
        capture_output=True,
        text=True,
        env=env,
    )


def stub_calls(tree: Path) -> str:
    log = tree / "stub.log"
    return log.read_text() if log.exists() else ""


def test_complete_key_set_is_kept_without_force(tree: Path) -> None:
    seed(tree, SIGNING + BOOT)
    before = snapshot(tree)
    result = run(tree)
    assert result.returncode == 0, result.stderr
    assert "pass --force to regenerate" in result.stdout
    assert snapshot(tree) == before
    assert stub_calls(tree) == ""


@pytest.mark.parametrize(
    "missing",
    ["DB.key", "PK.crt", "modules/linux-module-cert.crt", "sysupdate-signing.asc", "import-pubring.pgp"],
)
def test_partial_key_set_is_refused_without_force(tree: Path, missing: str) -> None:
    seed(tree, [name for name in SIGNING + BOOT if name != missing])
    before = snapshot(tree)
    result = run(tree)
    assert result.returncode == 1
    assert "partial" in result.stderr
    assert "--force" in result.stderr
    assert snapshot(tree) == before
    assert stub_calls(tree) == ""


def test_empty_key_file_counts_as_missing(tree: Path) -> None:
    seed(tree, SIGNING + BOOT)
    (tree / "files" / "boot-keys" / "KEK.key").write_text("")
    result = run(tree)
    assert result.returncode == 1
    assert "partial boot key set" in result.stderr
    assert stub_calls(tree) == ""


def test_force_regenerates_an_existing_set(tree: Path) -> None:
    seed(tree, SIGNING + BOOT)
    result = run(tree, "--force")
    assert result.returncode != 0, "the failing gpg stub must have been reached"
    assert stub_calls(tree).splitlines()[0] == "gpg"
