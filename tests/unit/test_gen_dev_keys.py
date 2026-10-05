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
DEV_KEYS = REPO_ROOT / "files" / "dev-keys"

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
    shutil.copytree(DEV_KEYS, tmp_path / "files" / "dev-keys")
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


def run(tree: Path, *args: str, real_openssl: bool = False) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    if real_openssl:
        (tree / "stubs" / "openssl").unlink(missing_ok=True)
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


def module_pair(tree: Path) -> tuple[bytes, bytes]:
    keys = tree / "files" / "boot-keys"
    return (keys / "linux-module-cert.key").read_bytes(), (keys / "modules" / "linux-module-cert.crt").read_bytes()


def test_module_key_is_the_committed_dev_pair(tree: Path) -> None:
    # A fixed module certificate keeps the kernel's cache key stable across
    # runs, so non-release builds pull the kernel instead of compiling it.
    seed(tree, SIGNING)
    result = run(tree, real_openssl=True)
    assert result.returncode == 0, result.stderr
    assert "INSECURE dev key" in result.stdout
    assert module_pair(tree) == (
        (DEV_KEYS / "INSECURE-dev-module-key.pem").read_bytes(),
        (DEV_KEYS / "INSECURE-dev-module-key.crt").read_bytes(),
    )
    keys = tree / "files" / "boot-keys"
    assert (keys / "linux-module-cert.key").stat().st_mode & 0o777 == 0o600
    assert not (keys / "modules" / "linux-module-cert.key").exists()
    assert sorted(p.name for p in (keys / "modules").iterdir()) == ["linux-module-cert.crt"]


def test_regenerating_keeps_the_module_certificate(tree: Path) -> None:
    (tree / "stubs" / "gpg").write_text("#!/bin/sh\necho key\n")
    assert run(tree, real_openssl=True).returncode == 0
    first_db, first_module = (tree / "files" / "boot-keys" / "DB.crt").read_bytes(), module_pair(tree)
    result = run(tree, "--force", real_openssl=True)
    assert result.returncode == 0, result.stderr
    assert (tree / "files" / "boot-keys" / "DB.crt").read_bytes() != first_db, "boot keys are fresh"
    assert module_pair(tree) == first_module, "the module pair is not"


def test_private_module_key_is_fresh_and_not_the_dev_pair(tree: Path) -> None:
    seed(tree, SIGNING)
    result = run(tree, "--private-module-key", real_openssl=True)
    assert result.returncode == 0, result.stderr
    key, cert = module_pair(tree)
    assert cert != (DEV_KEYS / "INSECURE-dev-module-key.crt").read_bytes()
    assert key != (DEV_KEYS / "INSECURE-dev-module-key.pem").read_bytes()
    assert "private module signing key" in result.stdout


def test_unknown_argument_is_refused(tree: Path) -> None:
    result = run(tree, "--frce")
    assert result.returncode == 2
    assert "usage" in result.stderr
    assert not (tree / "files" / "boot-keys").exists()
