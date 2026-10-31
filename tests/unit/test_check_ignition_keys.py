"""Behavior of scripts/check-ignition-keys.sh beyond the trust-root contracts.

test_ignition_keys.py covers why the Ignition config keyring is its own trust
root (missing keyring, shared keys, the --release rules). This file covers
the rest of the script's interface:

- KEY_DIR: a relative one resolves against the repository root whatever the
  caller's working directory; an absolute one is used as given; --release
  takes one too.
- Every failure exits 1 with a check-ignition-keys: message on stderr.
- An empty keyring file is missing. Each keyring must be OpenPGP data that
  holds a key: a signature staged in its place is refused, and an unreadable
  release keyring (import-pubring.pgp) fails rather than reading as "shares
  no key".
- A shared key is named by fingerprint; with --release the committed keyring
  is no exception.
- On success it reports how many keys the Ignition keyring holds.
- gpg runs in a throwaway GNUPGHOME, removed on exit: the caller's keyring is
  never touched.
"""


import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-ignition-keys.sh"


def _gpg(home: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(["gpg", "--batch", "--quiet", *args], check=True, capture_output=True,
                          env=dict(os.environ, GNUPGHOME=str(home)))


@pytest.fixture(scope="module")
def keys(gpg: str, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path | str]:
    """Public keyrings for three keys, each key's fingerprint, a two-key
    keyring, and a detached signature (OpenPGP data that holds no key)."""
    base = tmp_path_factory.mktemp("keys")
    out: dict[str, Path | str] = {}
    for name in ("config", "stranger", "release"):
        home = base / name
        home.mkdir(mode=0o700)
        _gpg(home, "--passphrase", "", "--quick-gen-key", name, "ed25519", "sign", "never")
        out[name] = base / f"{name}.pgp"
        _gpg(home, "--export", "--output", str(out[name]))
        colons = _gpg(home, "--with-colons", "--list-keys").stdout.decode()
        out[f"{name}-fpr"] = next(line.split(":")[9] for line in colons.splitlines() if line.startswith("fpr:"))
    out["two"] = base / "two.pgp"
    out["two"].write_bytes(Path(out["config"]).read_bytes() + Path(out["stranger"]).read_bytes())
    (payload := base / "payload").write_text("not a key\n")
    out["signature"] = base / "payload.gpg"
    _gpg(base / "config", "--detach-sign", "--output", str(out["signature"]), str(payload))
    return out


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "scripts")
    (repo / "files" / "release-keys").mkdir(parents=True)
    return repo


def stage(directory: Path, ignition: Path | bytes | None, release: Path | bytes | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, ring in (("ignition-pubring.pgp", ignition), ("import-pubring.pgp", release)):
        if isinstance(ring, Path):
            shutil.copy(ring, directory / name)
        elif isinstance(ring, bytes):
            (directory / name).write_bytes(ring)
    return directory


def check(checkout: Path, *args: str, cwd: Path | None = None,
          env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(checkout / "scripts" / SCRIPT.name), *args],
                          capture_output=True, text=True, cwd=cwd, env=env)


def test_a_relative_key_dir_resolves_against_the_repository(checkout: Path, keys: dict, tmp_path: Path) -> None:
    stage(checkout / "keys" / "ci", keys["config"], keys["release"])
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    result = check(checkout, "keys/ci", cwd=elsewhere)
    assert result.returncode == 0, result.stderr
    assert result.stdout == (
        "check-ignition-keys: keys/ci/ignition-pubring.pgp holds 1 key(s), none in keys/ci/import-pubring.pgp\n"
    )


def test_an_absolute_key_dir_is_used_as_given(checkout: Path, keys: dict, tmp_path: Path) -> None:
    outside = stage(tmp_path / "outside", keys["two"], keys["release"])
    result = check(checkout, str(outside))
    assert result.returncode == 0, result.stderr
    assert f"{outside}/ignition-pubring.pgp holds 2 key(s)" in result.stdout


def test_the_default_key_dir_is_files_boot_keys(checkout: Path, keys: dict, tmp_path: Path) -> None:
    stage(checkout / "files" / "boot-keys", keys["config"], keys["release"])
    result = check(checkout, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("check-ignition-keys: files/boot-keys/ignition-pubring.pgp holds 1 key(s)")


def test_an_empty_ignition_keyring_is_missing(checkout: Path, keys: dict) -> None:
    stage(checkout / "k", b"", keys["release"])
    result = check(checkout, "k")
    assert result.returncode == 1
    assert result.stderr.startswith("check-ignition-keys: missing k/ignition-pubring.pgp (just gen-dev-keys")


def test_openpgp_data_without_a_key_is_not_a_keyring(checkout: Path, keys: dict) -> None:
    stage(checkout / "k", keys["signature"], keys["release"])
    result = check(checkout, "k")
    assert result.returncode == 1
    assert result.stderr == "check-ignition-keys: k/ignition-pubring.pgp holds no OpenPGP key\n"


@pytest.mark.parametrize("ring", ["ignition", "import"])
def test_data_gpg_cannot_parse_is_refused(checkout: Path, keys: dict, ring: str) -> None:
    # An unreadable release keyring must not read as "shares no key".
    garbage = b"not OpenPGP data\n"
    if ring == "ignition":
        stage(checkout / "k", garbage, keys["release"])
    else:
        stage(checkout / "k", keys["config"], garbage)
    result = check(checkout, "k")
    assert result.returncode == 1
    assert result.stderr == f"check-ignition-keys: k/{ring}-pubring.pgp is not OpenPGP data\n"


def test_a_release_keyring_without_a_key_is_refused(checkout: Path, keys: dict) -> None:
    stage(checkout / "k", keys["config"], keys["signature"])
    result = check(checkout, "k")
    assert result.returncode == 1
    assert result.stderr == "check-ignition-keys: k/import-pubring.pgp holds no OpenPGP key\n"


@pytest.mark.parametrize("release", [None, b""], ids=["absent", "empty"])
def test_the_release_keyring_must_be_there(checkout: Path, keys: dict, release: bytes | None) -> None:
    stage(checkout / "k", keys["config"], release)
    result = check(checkout, "k")
    assert result.returncode == 1
    assert result.stderr == "check-ignition-keys: missing k/import-pubring.pgp\n"


def test_a_shared_key_is_named_by_fingerprint(checkout: Path, keys: dict) -> None:
    both = Path(keys["config"]).read_bytes() + Path(keys["release"]).read_bytes()
    stage(checkout / "k", both, keys["release"])
    result = check(checkout, "k")
    assert result.returncode == 1
    assert f"share keys ({keys['release-fpr']})" in result.stderr
    assert str(keys["config-fpr"]) not in result.stderr


def test_release_mode_takes_a_key_dir(checkout: Path, keys: dict) -> None:
    stage(checkout / "k", keys["config"], keys["release"])
    shutil.copy(keys["config"], checkout / "files" / "release-keys" / "ignition-pubring.pgp")
    result = check(checkout, "--release", "k")
    assert result.returncode == 0, result.stderr
    assert "k/ignition-pubring.pgp holds 1 key(s)" in result.stdout


def test_release_mode_names_the_keyring_it_expected(checkout: Path, keys: dict) -> None:
    stage(checkout / "k", keys["config"], keys["release"])
    shutil.copy(keys["stranger"], checkout / "files" / "release-keys" / "ignition-pubring.pgp")
    result = check(checkout, "--release", "k")
    assert result.returncode == 1
    assert result.stderr == "check-ignition-keys: k/ignition-pubring.pgp is not files/release-keys/ignition-pubring.pgp\n"


def test_a_committed_keyring_holding_the_release_key_is_still_refused(checkout: Path, keys: dict) -> None:
    both = Path(keys["config"]).read_bytes() + Path(keys["release"]).read_bytes()
    stage(checkout / "k", both, keys["release"])
    (checkout / "files" / "release-keys" / "ignition-pubring.pgp").write_bytes(both)
    result = check(checkout, "--release", "k")
    assert result.returncode == 1
    assert "share keys" in result.stderr


def test_the_callers_keyring_and_tmpdir_are_left_alone(checkout: Path, keys: dict, tmp_path: Path) -> None:
    stage(checkout / "k", keys["config"], keys["release"])
    caller = tmp_path / "caller-gnupg"
    caller.mkdir(mode=0o700)
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    result = check(checkout, "k", env=dict(os.environ, GNUPGHOME=str(caller), TMPDIR=str(scratch)))
    assert result.returncode == 0, result.stderr
    assert list(caller.iterdir()) == []
    assert list(scratch.iterdir()) == [], "the throwaway GNUPGHOME is removed on exit"
