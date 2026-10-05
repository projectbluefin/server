"""Behavior of scripts/publish-release.sh, the one publish path build.yml runs
on main (release) and on pull requests (release-dry-run)."""

from __future__ import annotations

import hashlib
import json
import os
import re
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
        f"homelab_{version}.raw.zst",
        f"argo-workflows_{version}.raw.zst",
        f"mcp_{version}.raw.zst",
        f"nvidia-open-595_{version}.raw.zst",
        "k0s-1.36.4-k0s.0.raw.zst",
        "nvidia-container-toolkit-1.20.1.raw.zst",
        *(f"{t}.{ext}" for t in HOMELAB_TEMPLATES for ext in ("bu", "ign")),
    ]


HOMELAB_TEMPLATES = (
    "homelab-control-plane",
    "homelab-node",
    "homelab-k0s-control-plane",
    "homelab-k0s-node",
)


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
    assert f"release set {VERSION}: 25 files match SHA256SUMS, signature verified" in result.stdout
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


FAKE_GH_RELEASES = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ["GH_CALLS"], "a") as calls:
    calls.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1:3] == ["release", "list"]:
    if os.environ.get("GH_LIST_FAILS"):
        sys.exit(1)
    print("\\n".join(os.environ["GH_TAGS"].split()))
"""


@pytest.fixture
def fake_gh(tmp_path: Path, monkeypatch) -> Path:
    """A gh that lists the releases in $GH_TAGS and records every call."""
    bin_dir = tmp_path / "gh-bin"
    bin_dir.mkdir()
    (bin_dir / "gh").write_text(FAKE_GH_RELEASES)
    (bin_dir / "gh").chmod(0o755)
    calls = tmp_path / "gh-calls"
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("GH_CALLS", str(calls))
    monkeypatch.setenv("GH_TAGS", "")
    monkeypatch.delenv("GH_LIST_FAILS", raising=False)
    return calls


def test_dry_run_renders_gh_release_for_top_level_files_only(release: Path, fake_gh: Path) -> None:
    result = run("release", str(release), VERSION, "--dry-run")
    assert result.returncode == 0, result.stderr
    command = result.stdout.splitlines()[-1]
    assert command.startswith(f"gh release create v{VERSION} --target {'0' * 40} ")
    for name in [*release_files(VERSION), "SHA256SUMS", "SHA256SUMS.gpg"]:
        assert f"{release}/{name}" in command
    assert "efi-keys" not in command


def test_release_notes_use_the_release_version_and_source(release: Path, tmp_path: Path, monkeypatch) -> None:
    # Capture the actual gh arguments without publishing anything. Run outside
    # the checkout to ensure the release text has no working-directory dependency.
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "gh-args.json"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env python3\n"
        "import json, os, sys\n"
        "with open(os.environ['GH_CAPTURE'], 'w') as out: json.dump(sys.argv[1:], out)\n"
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("GH_CAPTURE", str(capture))
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/server")
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://github.com")
    result = run("release", str(release), VERSION, cwd=tmp_path)
    assert result.returncode == 0, result.stderr
    args = json.loads(capture.read_text())
    notes = args[args.index("--notes") + 1]
    assert f"https://github.com/example/server/releases/download/v{VERSION}/bluefin-server-installer_{VERSION}.raw" in notes
    assert f"sudo dd if=bluefin-server-installer_{VERSION}.raw of=/dev/<usb>" in notes
    assert "sha256sum --check --ignore-missing SHA256SUMS" in notes
    assert "erases the entire USB stick" in notes
    assert "target disk is erased too" in notes
    assert f"https://github.com/example/server/blob/{'0' * 40}/docs/skills/usb-installer.md" in notes
    assert "```bash\n" in notes
    assert "${" not in notes
    assert args[args.index("--notes") + 2:] == [
        str(release / name)
        for name in sorted([*release_files(VERSION), "SHA256SUMS", "SHA256SUMS.gpg"])
    ]


@pytest.mark.parametrize(
    ("published", "flag"),
    [
        ("", "--latest"),
        ("v26.09.6 v26.08.30 v0.9 not-a-version", "--latest"),
        ("v26.09.7", "--latest"),
        # 26.09.12 is newer than 26.09.7 under sort -V (and strverscmp), not as text.
        ("v26.09.12 v26.09.6", "--latest=false"),
        ("v26.10.1", "--latest=false"),
    ],
    ids=["first", "newest", "same", "older-by-run", "older-by-month"],
)
def test_release_is_marked_latest_only_when_newest(release: Path, fake_gh: Path, monkeypatch, published: str, flag: str) -> None:
    monkeypatch.setenv("GH_TAGS", published)
    monkeypatch.setenv("GITHUB_REPOSITORY", "example/server")
    result = run("release", str(release), VERSION)
    assert result.returncode == 0, result.stderr
    calls = [json.loads(line) for line in fake_gh.read_text().splitlines()]
    assert calls[0][:7] == ["release", "list", "--repo", "example/server", "--exclude-drafts", "--exclude-pre-releases", "--limit"]
    create = calls[-1]
    assert create[:8] == ["release", "create", f"v{VERSION}", "--target", "0" * 40, "--title", f"Bluefin Server {VERSION}", flag]
    assert create[8] == "--notes"
    assert ("::notice title=Not the latest release::" in result.stdout) == (flag == "--latest=false")


def test_release_stops_when_the_releases_cannot_be_listed(release: Path, fake_gh: Path, monkeypatch) -> None:
    monkeypatch.setenv("GH_LIST_FAILS", "1")
    result = run("release", str(release), VERSION)
    assert result.returncode != 0
    assert "cannot list the releases of" in result.stderr
    assert [json.loads(line)[:2] for line in fake_gh.read_text().splitlines()] == [["release", "list"]]


# An in-memory OCI registry: enough of `oras push`, `resolve` and
# `manifest fetch` for publish-release.sh oci.
FAKE_ORAS = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
with open(os.environ["ORAS_CALLS"], "a") as calls:
    calls.write(" ".join(sys.argv[1:]) + "\n")
with open(os.environ["ORAS_STATE"]) as f:
    state = json.load(f)
args = [a for a in sys.argv[1:] if a != "--plain-http"]

def lookup(ref):
    if os.environ.get("ORAS_BROKEN"):
        sys.exit("Error: dial tcp: connection refused")
    digest = ref.split("@", 1)[1] if "@" in ref else state["tags"].get(ref.rsplit(":", 1)[1])
    if digest not in state["manifests"]:
        sys.exit(f'Error response from registry: failed to fetch the content of "{ref}": {ref}: not found')
    return digest

if args[0] == "push":
    i, annotations = 1, {}
    while args[i].startswith("--"):
        if args[i] == "--annotation":
            key, value = args[i + 1].split("=", 1)
            annotations[key] = value
        i += 2
    ref, files = args[i], args[i + 1:]
    layers = []
    for name in files:
        with open(name, "rb") as f:
            layers.append({"digest": "sha256:" + hashlib.sha256(f.read()).hexdigest(),
                           "annotations": {"org.opencontainers.image.title": name}})
    manifest = {"annotations": annotations, "layers": layers}
    digest = "sha256:" + hashlib.sha256(json.dumps(manifest).encode()).hexdigest()
    state["manifests"][digest] = manifest
    for tag in ref.rsplit(":", 1)[1].split(","):
        state["tags"][tag] = digest
    with open(os.environ["ORAS_STATE"], "w") as f:
        json.dump(state, f)
elif args[0] == "resolve":
    print(lookup(args[1]))
elif args[:2] == ["manifest", "fetch"]:
    print(json.dumps(state["manifests"][lookup(args[2])]))
else:
    sys.exit(f"fake oras: unsupported {args}")
'''

OCI_REF = "localhost:5000/bluefin-server"


def oci(release: Path, tmp_path: Path, latest: str | None, broken: bool = False) -> tuple[subprocess.CompletedProcess[str], dict, str]:
    bin_dir = tmp_path / "oras-bin"
    bin_dir.mkdir()
    (bin_dir / "oras").write_text(FAKE_ORAS)
    (bin_dir / "oras").chmod(0o755)
    state = {"tags": {}, "manifests": {}}
    if latest is not None:
        old = {"annotations": {"org.opencontainers.image.version": latest}, "layers": []}
        state = {"tags": {latest: "sha256:old", "latest": "sha256:old"}, "manifests": {"sha256:old": old}}
    files = {"state": tmp_path / "oras-state.json", "calls": tmp_path / "oras-calls"}
    files["state"].write_text(json.dumps(state))
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "ORAS_STATE": str(files["state"]),
        "ORAS_CALLS": str(files["calls"]),
        "GITHUB_SHA": "0" * 40,
    }
    env.pop("GITHUB_OUTPUT", None)
    if broken:
        env["ORAS_BROKEN"] = "1"
    result = subprocess.run(["bash", str(SCRIPT), "oci", str(release), VERSION, OCI_REF, "--plain-http"], env=env, capture_output=True, text=True)
    calls = files["calls"].read_text() if files["calls"].exists() else ""
    return result, json.loads(files["state"].read_text()), calls


@pytest.mark.parametrize("latest", [None, "26.09.6", "26.09.7", "26.08.30"], ids=["first", "older-by-run", "same", "older-by-month"])
def test_oci_moves_latest_to_a_newer_version(release: Path, tmp_path: Path, latest: str | None) -> None:
    result, state, _ = oci(release, tmp_path, latest)
    assert result.returncode == 0, result.stderr
    assert state["tags"]["latest"] == state["tags"][VERSION] != "sha256:old"
    assert "latest=true" in result.stdout.splitlines()


@pytest.mark.parametrize("latest", ["26.09.12", "26.10.1"], ids=["newer-by-run", "newer-by-month"])
def test_oci_never_moves_latest_backwards(release: Path, tmp_path: Path, latest: str) -> None:
    result, state, calls = oci(release, tmp_path, latest)
    assert result.returncode == 0, result.stderr
    assert state["tags"]["latest"] == "sha256:old"
    assert state["tags"][VERSION] not in ("sha256:old", None)
    assert f" {OCI_REF}:{VERSION} " in calls and f"{OCI_REF}:{VERSION},latest" not in calls
    assert f"::notice title=latest not moved::{OCI_REF}:latest stays at {latest}" in result.stdout
    assert "latest=false" in result.stdout.splitlines()


def test_oci_pushes_nothing_when_latest_cannot_be_read(release: Path, tmp_path: Path) -> None:
    result, state, calls = oci(release, tmp_path, "26.09.6", broken=True)
    assert result.returncode != 0
    assert f"cannot read {OCI_REF}:latest" in result.stderr
    assert "push" not in calls
    assert state["tags"]["latest"] == "sha256:old"


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
    git = ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
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


def test_a_missing_homelab_template_is_refused(release: Path, signers) -> None:
    # The templates are release assets like the images: a set without one
    # must not publish, or releases/latest/download/<template> breaks.
    names = [n for n in release_files(VERSION) if n != "homelab-node.ign"]
    (release / "homelab-node.ign").unlink()
    write_sums(release, names)
    signers[0].sign(release / "SHA256SUMS")
    result = verify(release, signers[0].keyring)
    assert result.returncode != 0
    assert "homelab-node\\.ign" in result.stderr


def test_the_image_stages_and_signs_every_homelab_template() -> None:
    image = (ROOT / "elements" / "oci" / "bluefin-server-image.bst").read_text(encoding="utf-8")
    assert "location: /homelab-templates" in image
    assert 'install -m644 -t "%{install-root}" /homelab-templates/*.bu /homelab-templates/*.ign' in image
    assert re.search(r"sha256sum --binary .*\*\.bu \*\.ign > SHA256SUMS", image)
    templates = sorted(p.stem for p in (ROOT / "files" / "homelab" / "templates").glob("*.bu"))
    assert templates == sorted(HOMELAB_TEMPLATES)
    listed = re.search(r"for t in ([a-z0-9 -]+); do", SCRIPT.read_text(encoding="utf-8"))
    assert listed is not None and sorted(listed[1].split()) == templates
