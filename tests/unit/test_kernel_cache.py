"""scripts/kernel-cache.sh: the kernel cache in the project CAS.

The CAS is publicly readable, so `seed` must refuse whenever the graph it
builds reaches the element that stages private keys, before it writes the
client credentials anywhere; it must build nothing when a remote already holds
every element; and the push config it hands BuildStream must authenticate
with the client certificate and leave no credential behind. `just` is stubbed.

Each variant stages exactly one committed certificate as the only file of
files/boot-keys/modules/ (whose import is pushed with the kernel): release
the release certificate, which must not be the dev one; dev the public
INSECURE dev certificate, never its private key.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "kernel-cache.sh"

# Records each build with the config its --config flag names, as BuildStream
# would read it from /src (the checkout).
JUST = """#!/bin/sh
case "$*" in
  *"--deps all"*) printf '%s\\n' $GRAPH ;;
  "bst artifact show"*) printf '%s\\n' "$STATES"; [ -z "$UNREACHABLE" ] || echo "$UNREACHABLE" >&2 ;;
  "bst build"*)
    echo "$*" >> "$LOG/built"
    conf="${BST_FLAGS##*--config /src/}"
    cp "$conf" "$LOG/buildstream.conf"
    cp "$(dirname "$conf")/client.key" "$LOG/client.key"
    ls -ld "$(dirname "$conf")" > "$LOG/auth-dir" ;;
esac
"""


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    # A copy of the scripts and committed certificates in an otherwise empty
    # checkout, which the script cds into.
    (tmp_path / "scripts").mkdir()
    for name in ("kernel-cache.sh", "check-release-keys.sh"):
        shutil.copy(ROOT / "scripts" / name, tmp_path / "scripts" / name)
    for d in ("release-keys", "dev-keys"):
        shutil.copytree(ROOT / "files" / d, tmp_path / "files" / d)
    return tmp_path


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "just").write_text(JUST, encoding="utf-8")
    (bin_dir / "just").chmod(0o755)
    (tmp_path / "log").mkdir()
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LOG": str(tmp_path / "log"),
        "GRAPH": "freedesktop-sdk.bst:components/linux.bst bluefin-server/keys/linux-module-cert.bst",
        "STATES": "  not cached freedesktop-sdk.bst:components/linux.bst\n   available freedesktop-sdk.bst:components/go.bst",
        "CASD_CLIENT_CERT": "-----BEGIN CERTIFICATE-----\ncert\n-----END CERTIFICATE-----",
        "CASD_CLIENT_KEY": "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----",
        "BST_FLAGS": "",
        "UNREACHABLE": "",
    }


def run(checkout: Path, env: dict[str, str], variant: str = "release") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(checkout / "scripts" / "kernel-cache.sh"), "seed", variant],
        env=env, capture_output=True, text=True,
    )


def staged(checkout: Path) -> dict[str, bytes]:
    modules = checkout / "files" / "boot-keys" / "modules"
    return {str(f.relative_to(modules)): f.read_bytes() for f in modules.rglob("*") if f.is_file()}


def leftovers(checkout: Path) -> list[Path]:
    return list(checkout.glob(".casd.*"))


def test_seed_refuses_a_graph_that_reaches_the_keys(checkout: Path, env: dict[str, str]) -> None:
    env["GRAPH"] += " bluefin-server/keys/boot-keys.bst"
    result = run(checkout, env)
    assert result.returncode != 0
    assert "refusing to publish" in result.stderr
    assert not (Path(env["LOG"]) / "built").exists()
    assert not leftovers(checkout)


@pytest.mark.parametrize("missing", ["CASD_CLIENT_CERT", "CASD_CLIENT_KEY"])
def test_seed_needs_both_credentials(checkout: Path, env: dict[str, str], missing: str) -> None:
    del env[missing]
    result = run(checkout, env)
    assert result.returncode != 0
    assert missing in result.stderr
    assert not (Path(env["LOG"]) / "built").exists()


def test_seed_refuses_to_build_when_the_push_remote_is_unreachable(checkout: Path, env: dict[str, str]) -> None:
    # BuildStream only warns, then would build for an hour and push nothing.
    env["UNREACHABLE"] = (
        "WARNING Failed to initialize remote https://cache.projectbluefin.io:11002: "
        "Remote initialisation failed with status UNAVAILABLE"
    )
    result = run(checkout, env)
    assert result.returncode != 0
    assert "refusing to build without pushing" in result.stderr
    assert not (Path(env["LOG"]) / "built").exists()
    assert not leftovers(checkout)


def test_seed_skips_elements_a_remote_already_holds(checkout: Path, env: dict[str, str]) -> None:
    env["STATES"] = env["STATES"].replace("not cached", " available")
    result = run(checkout, env)
    assert result.returncode == 0
    assert "already on a remote" in result.stdout
    assert not (Path(env["LOG"]) / "built").exists()
    assert not leftovers(checkout)


def test_seed_builds_elements_only_cached_locally(checkout: Path, env: dict[str, str]) -> None:
    # A local artifact may never have been pushed; `bst build` pushes it.
    env["STATES"] = env["STATES"].replace("not cached", "    cached")
    assert run(checkout, env).returncode == 0
    assert (Path(env["LOG"]) / "built").exists()


def test_seed_pushes_with_the_client_certificate(checkout: Path, env: dict[str, str]) -> None:
    result = run(checkout, env)
    assert result.returncode == 0, result.stderr
    log = Path(env["LOG"])
    assert (log / "built").read_text().split() == [
        "bst",
        "build",
        "freedesktop-sdk.bst:components/linux.bst",
        "freedesktop-sdk.bst:components/go.bst",
    ]
    conf = (log / "buildstream.conf").read_text()
    for kind in ("artifacts:", "source-caches:"):
        section = conf.split(kind, 1)[1]
        assert "url: https://cache.projectbluefin.io:11002" in section
        assert "push: true" in section
        assert "client-cert: /src/.casd." in section and "client-key: /src/.casd." in section
    assert (log / "client.key").read_text() == env["CASD_CLIENT_KEY"] + "\n"
    assert (log / "auth-dir").read_text().startswith("drwx------")
    assert not leftovers(checkout)


def test_fsdk_junction_patch_includes_bluefin_cas() -> None:
    patch = (ROOT / "patches" / "freedesktop-sdk" / "0001-project.conf-Add-GNOME-CAS-servers.patch").read_text()
    assert "+- url: https://cache.projectbluefin.io:11001" in patch
    assert patch.count("https://cache.projectbluefin.io:11001") == 2


@pytest.mark.parametrize(
    ("variant", "cert"),
    [("release", "release-keys/linux-module-cert.crt"), ("dev", "dev-keys/INSECURE-dev-module-key.crt")],
)
def test_seed_stages_only_the_variant_certificate(checkout: Path, env: dict[str, str], variant: str, cert: str) -> None:
    result = run(checkout, env, variant)
    assert result.returncode == 0, result.stderr
    assert staged(checkout) == {"linux-module-cert.crt": (ROOT / "files" / cert).read_bytes()}
    assert b"PRIVATE KEY" not in staged(checkout)["linux-module-cert.crt"]
    assert f"kernel-cache: {variant}: pushed" in result.stdout


@pytest.mark.parametrize("variant", ["release", "dev"])
def test_seed_refuses_anything_else_in_the_pushed_modules_import(
    checkout: Path, env: dict[str, str], variant: str
) -> None:
    modules = checkout / "files" / "boot-keys" / "modules"
    modules.mkdir(parents=True)
    shutil.copy(ROOT / "files" / "dev-keys" / "INSECURE-dev-module-key.pem", modules / "linux-module-cert.key")
    result = run(checkout, env, variant)
    assert result.returncode != 0
    assert "must hold only the certificate; refusing to publish" in result.stderr
    assert not (Path(env["LOG"]) / "built").exists()
    assert not leftovers(checkout)


def test_seed_release_refuses_the_dev_certificate(checkout: Path, env: dict[str, str]) -> None:
    shutil.copy(
        checkout / "files" / "dev-keys" / "INSECURE-dev-module-key.crt",
        checkout / "files" / "release-keys" / "linux-module-cert.crt",
    )
    result = run(checkout, env, "release")
    assert result.returncode != 0
    assert "INSECURE dev module certificate" in result.stderr
    assert not (Path(env["LOG"]) / "built").exists()


@pytest.mark.parametrize("args", [["seed"], ["seed", "prod"], ["build", "dev"], []])
def test_seed_needs_a_known_variant(checkout: Path, env: dict[str, str], args: list[str]) -> None:
    result = subprocess.run(
        ["bash", str(checkout / "scripts" / "kernel-cache.sh"), *args], env=env, capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "usage" in result.stderr
    assert not (Path(env["LOG"]) / "built").exists()
