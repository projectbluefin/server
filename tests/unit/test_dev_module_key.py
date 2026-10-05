"""The committed INSECURE dev module key never reaches a release.

files/dev-keys/ publishes a module signing pair so that every non-release
build trusts one certificate and pulls one cached kernel. Release builds must
refuse it: scripts/check-release-keys.sh fails on the dev certificate, on the
dev private key and on a certificate re-issued for that key; build.yml runs it
on every release key set; the committed release certificate is not the dev
one; and no element stages files/dev-keys/, so the published private key ships
in no artifact.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DEV_KEYS = ROOT / "files" / "dev-keys"
DEV_CERT = DEV_KEYS / "INSECURE-dev-module-key.crt"
DEV_KEY = DEV_KEYS / "INSECURE-dev-module-key.pem"
RELEASE_CERT = ROOT / "files" / "release-keys" / "linux-module-cert.crt"
WORKFLOW = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text())


def pubkey(*args: str) -> str:
    return subprocess.run(["openssl", *args], check=True, capture_output=True, text=True).stdout


def new_pair(directory: Path, key: Path | None = None) -> None:
    """A module pair in directory; with `key`, a new certificate for that key."""
    (directory / "modules").mkdir(parents=True, exist_ok=True)
    key_args = ["-key", str(key)] if key else ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-256", "-nodes",
                                               "-keyout", str(directory / "linux-module-cert.key")]
    subprocess.run(
        ["openssl", "req", "-new", "-x509", "-days", "1", "-subj", "/CN=test/", *key_args,
         "-out", str(directory / "modules" / "linux-module-cert.crt")],
        check=True, capture_output=True,
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    (tmp_path / "scripts").mkdir()
    shutil.copy(ROOT / "scripts" / "check-release-keys.sh", tmp_path / "scripts")
    shutil.copytree(DEV_KEYS, tmp_path / "files" / "dev-keys")
    return tmp_path


def check(checkout: Path, key_dir: str = "files/boot-keys") -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(checkout / "scripts" / "check-release-keys.sh"), key_dir],
                          capture_output=True, text=True)


def test_a_project_key_set_passes(checkout: Path) -> None:
    new_pair(checkout / "files" / "boot-keys")
    result = check(checkout)
    assert result.returncode == 0, result.stderr


def test_the_release_certificate_alone_passes(checkout: Path) -> None:
    # The kernel cache seed stages only the certificate.
    modules = checkout / "files" / "boot-keys" / "modules"
    modules.mkdir(parents=True)
    shutil.copy(RELEASE_CERT, modules / "linux-module-cert.crt")
    result = check(checkout)
    assert result.returncode == 0, result.stderr


def test_the_dev_certificate_fails(checkout: Path) -> None:
    keys = checkout / "files" / "boot-keys"
    new_pair(keys)
    shutil.copy(DEV_CERT, keys / "modules" / "linux-module-cert.crt")
    result = check(checkout)
    assert result.returncode != 0
    assert "INSECURE dev module certificate" in result.stderr


def test_the_dev_private_key_fails(checkout: Path) -> None:
    keys = checkout / "files" / "boot-keys"
    new_pair(keys)
    shutil.copy(DEV_KEY, keys / "linux-module-cert.key")
    result = check(checkout)
    assert result.returncode != 0
    assert "INSECURE dev module key" in result.stderr


def test_a_certificate_reissued_for_the_dev_key_fails(checkout: Path) -> None:
    keys = checkout / "files" / "boot-keys"
    new_pair(keys, key=DEV_KEY)
    assert (keys / "modules" / "linux-module-cert.crt").read_bytes() != DEV_CERT.read_bytes()
    (keys / "linux-module-cert.key").unlink(missing_ok=True)
    result = check(checkout)
    assert result.returncode != 0
    assert "INSECURE dev module certificate" in result.stderr


@pytest.mark.parametrize("content", [None, b"", b"not a certificate\n"])
def test_a_missing_or_broken_certificate_fails(checkout: Path, content: bytes | None) -> None:
    modules = checkout / "files" / "boot-keys" / "modules"
    modules.mkdir(parents=True)
    if content is not None:
        (modules / "linux-module-cert.crt").write_bytes(content)
    assert check(checkout).returncode != 0


def test_the_committed_pairs() -> None:
    dev = pubkey("x509", "-in", str(DEV_CERT), "-noout", "-pubkey")
    assert dev == pubkey("pkey", "-in", str(DEV_KEY), "-pubout"), "the dev certificate is for the dev key"
    assert dev != pubkey("x509", "-in", str(RELEASE_CERT), "-noout", "-pubkey"), "release must not be the dev key"
    readme = (DEV_KEYS / "README.md").read_text()
    assert "INSECURE" in readme and "published private key" in readme
    assert sorted(p.name for p in DEV_KEYS.iterdir()) == [
        "INSECURE-dev-module-key.crt", "INSECURE-dev-module-key.pem", "README.md"
    ]


def test_no_element_stages_the_dev_keys() -> None:
    for element in (ROOT / "elements").rglob("*.bst"):
        doc = yaml.safe_load(element.read_text()) or {}
        for source in doc.get("sources") or []:
            path = str(source.get("path", "")).rstrip("/") if isinstance(source, dict) else ""
            if path:
                assert not ("files/dev-keys/".startswith(path + "/") or path.startswith("files/dev-keys")), (
                    f"{element.relative_to(ROOT)} stages {path}, which holds the published dev private key"
                )


def test_release_builds_check_their_keys_after_staging_them() -> None:
    (step,) = [s for s in WORKFLOW["jobs"]["build"]["steps"] if s.get("name") == "Install signing keys"]
    release_branch = step["run"].split("else", 1)[0]
    staged = release_branch.index("cp files/release-keys/linux-module-cert.crt")
    assert release_branch.index("bash scripts/check-release-keys.sh") > staged


def test_both_kernel_variants_are_seeded_on_releases_and_only_release_gates_the_build() -> None:
    jobs = WORKFLOW["jobs"]
    for job, variant in (("kernel-cache", "release"), ("kernel-cache-dev", "dev")):
        assert jobs[job]["if"] == "needs.changes.outputs.release == 'true'"
        runs = [s.get("run", "") for s in jobs[job]["steps"]]
        assert f"bash scripts/kernel-cache.sh seed {variant}" in runs
        assert "BOOT_KEYS_TARBALL" not in str(jobs[job]) and "SYSUPDATE_SIGNING_KEY" not in str(jobs[job])
        assert "gen-dev-keys" not in str(jobs[job])
    assert "kernel-cache" in jobs["build"]["needs"]
    assert not any("kernel-cache-dev" in str(j.get("needs", "")) for j in jobs.values())
