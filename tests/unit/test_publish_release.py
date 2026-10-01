"""Behavior of scripts/publish-release.sh, the one publish path build.yml runs
on main (release) and on pull requests (release-dry-run)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "publish-release.sh"
VERSION = "26.09.7"
UUID_A = "d3107d37-a9da-32cf-3c19-49fa3b0cb1df"
UUID_B = "7c6a26c3-2990-8ab6-966f-1e38b85bcd4e"
SPDX = {
    "spdxVersion": "SPDX-2.3",
    "creationInfo": {"created": "2026-09-28T00:00:00Z"},
    "packages": [{"SPDXID": "SPDXRef-a-0", "name": "systemd", "versionInfo": "260"}],
}

pytestmark = pytest.mark.skipif(shutil.which("gpg") is None, reason="needs gpg")


def release_files(version: str) -> list[str]:
    return [
        f"bluefin-server_{version}.raw",
        f"bluefin-server_{version}_{UUID_A}.usr.raw",
        f"bluefin-server_{version}_{UUID_B}.usr-verity.raw",
        f"bluefin-server-{version}.efi",
        f"bluefin-server-netboot_{version}.efi",
        f"bluefin-server-netboot_{version}.esp.raw",
        f"bluefin-server-installer_{version}.raw",
        f"bluefin-server_{version}.spdx.json",
        f"zfs_{version}.raw.zst",
        f"kubestellar_{version}.raw.zst",
        f"kubeadm_{version}.raw.zst",
        f"server-kubernetes_{version}.raw",
        f"server-containerd_{version}.raw",
        f"server_{version}.raw.zst",
        f"server-bundle_{version}.tar.zst",
        f"nvidia-open-595_{version}.raw.zst",
        "k0s-1.36.4-k0s.0.raw.zst",
        "nvidia-container-toolkit-1.20.1.raw.zst",
    ]


class Signer:
    def __init__(self, home: Path) -> None:
        self.env = {**os.environ, "GNUPGHOME": str(home)}
        home.chmod(0o700)
        self.gpg("--quick-gen-key", "Test Release <release@example.invalid>", "ed25519", "sign", "never")
        self.keyring = home / "import-pubring.pgp"
        self.gpg("--output", str(self.keyring), "--export", "release@example.invalid")

    def gpg(self, *args: str) -> None:
        subprocess.run(
            ["gpg", "--batch", "--quiet", "--yes", "--pinentry-mode", "loopback", "--passphrase", "", *args],
            env=self.env,
            check=True,
            capture_output=True,
        )

    def sign(self, sums: Path) -> None:
        self.gpg("--detach-sign", "--output", f"{sums}.gpg", str(sums))

    def close(self) -> None:
        subprocess.run(["gpgconf", "--kill", "all"], env=self.env, check=False, capture_output=True)


@pytest.fixture(scope="module")
def signers():
    homes = [Path(tempfile.mkdtemp(prefix="gpg", dir="/tmp")) for _ in range(2)]
    made = [Signer(home) for home in homes]
    yield made
    for signer, home in zip(made, homes):
        signer.close()
        shutil.rmtree(home, ignore_errors=True)


def write_sums(release: Path, names: list[str]) -> None:
    lines = [f"{hashlib.sha256((release / n).read_bytes()).hexdigest()} *{n}\n" for n in names]
    (release / "SHA256SUMS").write_text("".join(lines))


@pytest.fixture
def release(tmp_path: Path, signers) -> Path:
    out = tmp_path / "diskless"
    out.mkdir()
    names = release_files(VERSION)
    for name in names:
        (out / name).write_text(f"content of {name}\n")
    (out / f"bluefin-server_{VERSION}.spdx.json").write_text(json.dumps(SPDX))
    (out / "efi-keys").mkdir()
    (out / "efi-keys" / "db.auth").write_text("not published\n")
    write_sums(out, names)
    signers[0].sign(out / "SHA256SUMS")
    return out


def run(*args: str, cwd: Path | None = None, tmp: Path | None = None) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "GITHUB_SHA": "0" * 40}
    env.pop("GITHUB_OUTPUT", None)
    if tmp is not None:
        env["RUNNER_TEMP"] = str(tmp)
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=cwd, env=env, capture_output=True, text=True)


def verify(release: Path, keyring: Path, version: str = VERSION) -> subprocess.CompletedProcess[str]:
    return run("verify", str(release), version, str(keyring), tmp=release.parent)


def test_complete_release_set_verifies(release: Path, signers) -> None:
    result = verify(release, signers[0].keyring)
    assert result.returncode == 0, result.stderr
    subjects = release.parent / f"release-subjects-{VERSION}.sha256"
    assert f"subjects={subjects}" in result.stdout
    names = sorted(line.split("  ", 1)[1] for line in subjects.read_text().splitlines())
    assert names == sorted([*release_files(VERSION), "SHA256SUMS", "SHA256SUMS.gpg"])


def test_missing_file_is_refused(release: Path, signers) -> None:
    (release / f"zfs_{VERSION}.raw.zst").unlink()
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert f"listed in SHA256SUMS but missing: zfs_{VERSION}.raw.zst" in result.stderr


def test_bad_checksum_is_refused(release: Path, signers) -> None:
    (release / f"bluefin-server_{VERSION}.raw").write_text("tampered\n")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "checksum mismatch" in result.stderr


def test_rehashed_unsigned_manifest_is_refused(release: Path, signers) -> None:
    (release / f"bluefin-server_{VERSION}.raw").write_text("tampered\n")
    write_sums(release, release_files(VERSION))
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "SHA256SUMS.gpg does not verify" in result.stderr


def test_signature_from_another_key_is_refused(release: Path, signers) -> None:
    signers[1].sign(release / "SHA256SUMS")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "SHA256SUMS.gpg does not verify" in result.stderr


def test_version_mismatch_is_refused(release: Path, signers) -> None:
    result = verify(release, signers[0].keyring, version="26.09.8")
    assert result.returncode != 0
    assert "is not a file of release 26.09.8" in result.stderr


def test_file_of_another_version_is_refused(release: Path, signers) -> None:
    names = release_files(VERSION)
    old = f"kubeadm_{VERSION}.raw.zst"
    new = "kubeadm_26.09.6.raw.zst"
    (release / old).rename(release / new)
    write_sums(release, [new if n == old else n for n in names])
    signers[0].sign(release / "SHA256SUMS")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert f"{new} is not a file of release {VERSION}" in result.stderr


def test_missing_artifact_kind_is_refused(release: Path, signers) -> None:
    names = [n for n in release_files(VERSION) if not n.endswith(".spdx.json")]
    (release / f"bluefin-server_{VERSION}.spdx.json").unlink()
    write_sums(release, names)
    signers[0].sign(release / "SHA256SUMS")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "needs exactly one file matching bluefin-server_26\\.09\\.7\\.spdx\\.json, found 0" in result.stderr


@pytest.mark.parametrize(
    "broken",
    [{"creationInfo": {}}, {"packages": [*SPDX["packages"], *SPDX["packages"]]}, {"spdxVersion": "SPDX-2.2"}],
    ids=["no-created", "duplicate-spdxid", "wrong-version"],
)
def test_invalid_sbom_is_refused(release: Path, signers, broken: dict) -> None:
    sbom = release / f"bluefin-server_{VERSION}.spdx.json"
    sbom.write_text(json.dumps({**SPDX, **broken}))
    write_sums(release, release_files(VERSION))
    signers[0].sign(release / "SHA256SUMS")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "is not an SPDX 2.3 document" in result.stderr


def test_unsigned_top_level_file_is_refused(release: Path, signers) -> None:
    (release / "dogfood-serial.log").write_text("local leftovers\n")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "not covered by SHA256SUMS: dogfood-serial.log" in result.stderr


def test_dry_run_renders_gh_release_for_top_level_files_only(release: Path) -> None:
    result = run("release", str(release), VERSION, "--dry-run")
    assert result.returncode == 0, result.stderr
    command = result.stdout.splitlines()[-1]
    assert command.startswith(f"gh release create v{VERSION} --target {'0' * 40} ")
    for name in [*release_files(VERSION), "SHA256SUMS", "SHA256SUMS.gpg"]:
        assert f"{release}/{name}" in command
    assert "efi-keys" not in command


WORKFLOW_REF = "projectbluefin/server/.github/workflows/build.yml@refs/heads/main"
FAKE_GH = """#!/bin/sh
printf '%s\\n' "$*" >> "$GH_CALLS"
[ -n "$GH_BLOB" ] || exit 1
echo "$GH_BLOB"
"""


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, str, str]:
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / ".github" / "workflows" / "build.yml").write_text("name: build\n")
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
           "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "add", "."], check=True)
    subprocess.run([*git, "commit", "-qm", "build"], check=True)
    sha = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    blob = subprocess.run([*git, "rev-parse", "HEAD:.github/workflows/build.yml"], check=True, capture_output=True, text=True).stdout.strip()
    return repo, sha, blob


def taggable(checkout: tuple[Path, str, str], default_branch_blob: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], dict[str, str]]:
    repo, sha, _ = checkout
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH)
    (bin_dir / "gh").chmod(0o755)
    files = {name: tmp_path / name for name in ("calls", "output", "summary")}
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "GH_CALLS": str(files["calls"]),
        "GH_BLOB": default_branch_blob,
        "GITHUB_SHA": sha,
        "GITHUB_REPOSITORY": "projectbluefin/server",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "GITHUB_OUTPUT": str(files["output"]),
        "GITHUB_STEP_SUMMARY": str(files["summary"]),
    }
    result = subprocess.run(["bash", str(SCRIPT), "taggable", VERSION], cwd=repo, env=env, capture_output=True, text=True)
    return result, {name: path.read_text() if path.exists() else "" for name, path in files.items()}


def test_commit_with_the_default_branch_workflow_is_published(checkout, tmp_path: Path) -> None:
    result, out = taggable(checkout, checkout[2], tmp_path)
    assert result.returncode == 0, result.stderr
    assert out["output"] == "publish=true\n"
    assert out["calls"] == "api repos/projectbluefin/server/contents/.github/workflows/build.yml --jq .sha\n"
    assert "::warning" not in result.stdout


def test_commit_whose_workflow_changed_on_the_default_branch_is_skipped(checkout, tmp_path: Path) -> None:
    result, out = taggable(checkout, "f" * 40, tmp_path)
    assert result.returncode == 0, result.stderr
    assert out["output"] == "publish=false\n"
    assert f"::warning title=Release skipped::v{VERSION} is not published" in result.stdout
    assert f"v{VERSION} is not published" in out["summary"]


@pytest.mark.parametrize("blob", ["", "not-a-blob"], ids=["api-error", "bad-response"])
def test_unreadable_default_branch_workflow_fails_instead_of_skipping(checkout, tmp_path: Path, blob: str) -> None:
    result, out = taggable(checkout, blob, tmp_path)
    assert result.returncode != 0
    assert "publish=" not in out["output"]
