"""The Ignition config keyring is its own trust root.

The initrd verifies a network-booted node's bluefin-node.ign.gpg against
ignition-pubring.pgp alone. scripts/check-ignition-keys.sh fails a key set
whose Ignition keyring is missing or shares a key with the release keyring
(import-pubring.pgp, which authenticates SHA256SUMS); with --release it also
requires the committed files/release-keys/ignition-pubring.pgp and no
Ignition secret key. build.yml runs it on every key set.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "check-ignition-keys.sh"
RELEASE_IGNITION = ROOT / "files" / "release-keys" / "ignition-pubring.pgp"
RELEASE_IMPORT = ROOT / "files" / "os" / "sysupdate-keys" / "import-pubring.gpg"
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text())

pytestmark = pytest.mark.skipif(not shutil.which("gpg"), reason="needs gpg")


@pytest.fixture(scope="module")
def rings(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("rings")
    out = {}
    for name in ("config", "release"):
        home = base / name
        home.mkdir(mode=0o700)
        env = dict(os.environ, GNUPGHOME=str(home))
        subprocess.run(
            ["gpg", "--batch", "--quiet", "--passphrase", "", "--quick-gen-key", name, "ed25519", "sign", "never"],
            check=True, env=env, capture_output=True,
        )
        out[name] = base / f"{name}.pgp"
        subprocess.run(["gpg", "--batch", "--export", "--output", str(out[name])], check=True, env=env)
    out["both"] = base / "both.pgp"
    out["both"].write_bytes(out["config"].read_bytes() + out["release"].read_bytes())
    return out


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(SCRIPT, tmp_path / "scripts")
    (tmp_path / "files" / "boot-keys").mkdir(parents=True)
    (tmp_path / "files" / "release-keys").mkdir()
    return tmp_path


def stage(checkout: Path, *, ignition: Path | None, release: Path) -> Path:
    keys = checkout / "files" / "boot-keys"
    if ignition is not None:
        shutil.copy(ignition, keys / "ignition-pubring.pgp")
    shutil.copy(release, keys / "import-pubring.pgp")
    return keys


def check(checkout: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(checkout / "scripts" / SCRIPT.name), *args], capture_output=True, text=True)


def test_a_separate_ignition_key_passes(checkout: Path, rings: dict[str, Path]) -> None:
    stage(checkout, ignition=rings["config"], release=rings["release"])
    result = check(checkout)
    assert result.returncode == 0, result.stderr
    assert "1 key(s), none in" in result.stdout


def test_a_missing_ignition_keyring_fails(checkout: Path, rings: dict[str, Path]) -> None:
    stage(checkout, ignition=None, release=rings["release"])
    result = check(checkout)
    assert result.returncode == 1
    assert "missing files/boot-keys/ignition-pubring.pgp" in result.stderr


@pytest.mark.parametrize("ignition", ["release", "both"])
def test_the_release_key_is_never_an_ignition_key(checkout: Path, rings: dict[str, Path], ignition: str) -> None:
    stage(checkout, ignition=rings[ignition], release=rings["release"])
    result = check(checkout)
    assert result.returncode == 1
    assert "share keys" in result.stderr


def test_a_release_build_needs_the_committed_keyring(checkout: Path, rings: dict[str, Path]) -> None:
    stage(checkout, ignition=rings["config"], release=rings["release"])
    result = check(checkout, "--release")
    assert result.returncode == 1
    assert "missing files/release-keys/ignition-pubring.pgp" in result.stderr

    shutil.copy(rings["config"], checkout / "files" / "release-keys" / "ignition-pubring.pgp")
    result = check(checkout, "--release")
    assert result.returncode == 0, result.stderr


def test_a_release_build_refuses_another_keyring(checkout: Path, rings: dict[str, Path]) -> None:
    stage(checkout, ignition=rings["config"], release=rings["release"])
    shutil.copy(rings["both"], checkout / "files" / "release-keys" / "ignition-pubring.pgp")
    result = check(checkout, "--release")
    assert result.returncode == 1


def test_a_release_build_refuses_the_ignition_secret_key(checkout: Path, rings: dict[str, Path]) -> None:
    keys = stage(checkout, ignition=rings["config"], release=rings["release"])
    shutil.copy(rings["config"], checkout / "files" / "release-keys" / "ignition-pubring.pgp")
    (keys / "ignition-signing.asc").write_text("secret\n")
    result = check(checkout, "--release")
    assert result.returncode == 1
    assert "must never be part of a release build" in result.stderr


def test_the_committed_release_keyrings_share_no_key(checkout: Path) -> None:
    shutil.copy(RELEASE_IGNITION, checkout / "files" / "release-keys" / "ignition-pubring.pgp")
    stage(checkout, ignition=RELEASE_IGNITION, release=RELEASE_IMPORT)
    result = check(checkout, "--release")
    assert result.returncode == 0, result.stderr


def test_every_build_checks_its_ignition_keyring_after_staging_it() -> None:
    (step,) = [s for s in WORKFLOW["jobs"]["build"]["steps"] if s.get("name") == "Install signing keys"]
    release_branch, dev_branch = step["run"].split("\nelse\n", 1)
    staged = release_branch.index("cp files/release-keys/ignition-pubring.pgp files/boot-keys/ignition-pubring.pgp")
    assert release_branch.index("rm -f files/boot-keys/ignition-signing.asc") < staged
    assert release_branch.index("bash scripts/check-ignition-keys.sh --release") > staged
    assert dev_branch.index("bash scripts/check-ignition-keys.sh") > dev_branch.index("just gen-dev-keys")
