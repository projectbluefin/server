"""Behavior of scripts/sign-node-config.sh, the operator's way to sign a
per-node Ignition config (docs/skills/booty-integration.md).

test_ignition_credentials.py shows a node accepts what it signs; this file
covers the script itself:

- It writes a binary, detached OpenPGP signature over exactly the config's
  bytes, by default to <config>.gpg, or to the third argument; an existing
  signature is replaced. gpgv with only the signer's public key verifies it.
- It verifies the signature before it succeeds; a failed verification fails
  the script.
- The key is imported into a throwaway GNUPGHOME: the caller's keyring is
  never read or written, and the temporary home is removed on success and
  on failure.
- Missing arguments print the usage and fail. A key file that is not an
  OpenPGP key, a public key only, a passphrase-protected key, a missing
  config or an unwritable signature path fails without a signature.
"""


import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sign-node-config.sh"
CONFIG = '{"ignition":{"version":"3.6.0"}}\n'


def _gpg(home: Path, *args: str) -> bytes:
    return subprocess.run(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", *args], check=True,
                          capture_output=True, env=dict(os.environ, GNUPGHOME=str(home))).stdout


@pytest.fixture(scope="module")
def keys(gpg: str, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """Armored secret keys for an unprotected and a passphrase-protected key,
    and each key's binary public keyring."""
    base = tmp_path_factory.mktemp("keys")
    out = {}
    for name, passphrase in (("config", ""), ("locked", "secret")):
        home = base / name
        home.mkdir(mode=0o700)
        _gpg(home, "--passphrase", passphrase, "--quick-gen-key", name, "ed25519", "sign", "never")
        out[name] = base / f"{name}.asc"
        out[name].write_bytes(_gpg(home, "--passphrase", passphrase, "--armor", "--export-secret-keys"))
        out[f"{name}-pub"] = base / f"{name}.pgp"
        out[f"{name}-pub"].write_bytes(_gpg(home, "--export"))
    return out


@pytest.fixture
def config(tmp_path: Path) -> Path:
    path = tmp_path / "bluefin-node.ign"
    path.write_text(CONFIG, encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    """A caller keyring and TMPDIR the script must leave empty."""
    caller = tmp_path / "caller-gnupg"
    caller.mkdir(mode=0o700)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    return dict(os.environ, GNUPGHOME=str(caller), TMPDIR=str(scratch))


def sign(*args: Path | str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), *map(str, args)], capture_output=True, text=True, env=env)


def verify(gpgv: str, keyring: Path, sig: Path, data: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([gpgv, "--keyring", str(keyring), str(sig), str(data)], capture_output=True, text=True)


def assert_left_alone(env: dict[str, str]) -> None:
    assert list(Path(env["GNUPGHOME"]).iterdir()) == [], "the caller's keyring is never touched"
    assert list(Path(env["TMPDIR"]).iterdir()) == [], "the throwaway GNUPGHOME is removed on exit"


def test_a_detached_binary_signature_lands_next_to_the_config(
    keys: dict[str, Path], config: Path, env: dict[str, str], gpgv: str,
) -> None:
    result = sign(keys["config"], config, env=env)
    assert result.returncode == 0, result.stderr
    assert 'Good signature from "config"' in result.stderr, "the script verifies what it wrote"
    sig = config.with_name("bluefin-node.ign.gpg")
    assert not sig.read_bytes().startswith(b"-----BEGIN"), "a node reads a binary signature"
    assert config.read_text(encoding="utf-8") == CONFIG, "the signature is detached; the config is untouched"
    verified = verify(gpgv, keys["config-pub"], sig, config)
    assert verified.returncode == 0, verified.stderr
    assert_left_alone(env)


def test_the_signature_covers_exactly_the_config_bytes(
    keys: dict[str, Path], config: Path, gpgv: str,
) -> None:
    assert sign(keys["config"], config).returncode == 0
    config.write_text(CONFIG + " ", encoding="utf-8")
    verified = verify(gpgv, keys["config-pub"], config.with_name("bluefin-node.ign.gpg"), config)
    assert verified.returncode != 0
    assert "BAD signature" in verified.stderr


def test_another_key_does_not_verify_it(keys: dict[str, Path], config: Path, gpgv: str) -> None:
    assert sign(keys["config"], config).returncode == 0
    verified = verify(gpgv, keys["locked-pub"], config.with_name("bluefin-node.ign.gpg"), config)
    assert verified.returncode != 0


def test_an_explicit_signature_path_is_used_and_replaced(
    keys: dict[str, Path], config: Path, tmp_path: Path, gpgv: str,
) -> None:
    sig = tmp_path / "served" / "node.sig"
    sig.parent.mkdir()
    sig.write_bytes(b"stale")
    result = sign(keys["config"], config, sig)
    assert result.returncode == 0, result.stderr
    assert not config.with_name("bluefin-node.ign.gpg").exists()
    assert verify(gpgv, keys["config-pub"], sig, config).returncode == 0


def test_a_failed_self_verification_fails_the_script(
    gpg: str, keys: dict[str, Path], config: Path, tmp_path: Path, env: dict[str, str],
) -> None:
    stubs = tmp_path / "bin"
    stubs.mkdir()
    stub = stubs / "gpg"
    stub.write_text(f'#!/bin/sh\nfor arg; do [ "$arg" = --verify ] && exit 1; done\nexec {gpg} "$@"\n')
    stub.chmod(0o755)
    result = sign(keys["config"], config, env=env | {"PATH": f"{stubs}:{env['PATH']}"})
    assert result.returncode == 1
    assert_left_alone(env)


@pytest.mark.parametrize("args", [(), ("key.asc",)], ids=["no-arguments", "no-config"])
def test_missing_arguments_print_the_usage(args: tuple[str, ...], tmp_path: Path) -> None:
    result = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 1
    assert "usage: " in result.stderr
    assert "<secret key> <config> [<signature>]" in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("key", ["not-a-key", "public-only", "passphrase", "missing"])
def test_a_key_that_cannot_sign_leaves_no_signature(
    keys: dict[str, Path], config: Path, env: dict[str, str], key: str,
) -> None:
    path = {
        "not-a-key": config,
        "public-only": keys["config-pub"],
        "passphrase": keys["locked"],
        "missing": config.with_name("absent.asc"),
    }[key]
    result = sign(path, config, env=env)
    assert result.returncode != 0
    assert not config.with_name("bluefin-node.ign.gpg").exists()
    assert_left_alone(env)


def test_a_missing_config_leaves_no_signature(keys: dict[str, Path], tmp_path: Path, env: dict[str, str]) -> None:
    config = tmp_path / "absent.ign"
    result = sign(keys["config"], config, env=env)
    assert result.returncode != 0
    assert not config.with_name("absent.ign.gpg").exists()
    assert_left_alone(env)


def test_an_unwritable_signature_path_fails(
    keys: dict[str, Path], config: Path, tmp_path: Path, env: dict[str, str],
) -> None:
    result = sign(keys["config"], config, tmp_path / "no-such-dir" / "sig.gpg", env=env)
    assert result.returncode != 0
    assert "can't create" in result.stderr
    assert_left_alone(env)
