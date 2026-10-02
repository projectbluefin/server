"""scripts/kernel-cache.sh: the public ghcr.io kernel cache.

The pushed tarball is public, so `seed` must refuse whenever the graph it
builds reaches the element that stages private keys; `restore` must never fail
a release build; and what `seed` packs must come back byte for byte in an
empty cache directory. The tarball also feeds the signed release, so `restore`
must pull only a digest that this repository's build workflow attested, and
`seed` must replace a tag that lacks that attestation. `just`, `oras` and `gh`
are stubbed; tar, zstd and split are real.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "kernel-cache.sh"
KEYS = ["a" * 64, "b" * 64]
DIGEST = "sha256:" + "c" * 64

JUST = """#!/bin/sh
case "$*" in
  *"--deps none"*) printf '%s\\n' {keys} ;;
  *"--deps all"*) printf '%s\\n' $GRAPH ;;
  "bst build"*) echo "$*" >> "$LOG/built"; mkdir -p "$HOME/.cache/buildstream/cas" "$HOME/.cache/buildstream/logs";
                printf 'kernel' > "$HOME/.cache/buildstream/cas/obj"; printf 'log' > "$HOME/.cache/buildstream/logs/l" ;;
esac
""".replace("{keys}", " ".join(KEYS))

# The tag "exists" when EXISTS is set or something was pushed to the store.
ORAS = """#!/bin/sh
case "$1 $2" in
  "manifest fetch") echo "$*" >> "$LOG/oras"; { [ -n "$EXISTS" ] || [ -n "$(ls "$STORE")" ]; } && printf '{"digest":"%s"}\\n' "{digest}" ;;
  "push "*) echo "$*" >> "$LOG/oras"; shift; while [ "${1#-}" != "$1" ]; do shift 2; done; shift; cp "$@" "$STORE/"; echo push >> "$LOG/pushed"; printf '{"digest":"%s"}\\n' "{digest}" ;;
  "pull -o") echo "$*" >> "$LOG/oras"; [ -n "$(ls "$STORE")" ] && cp "$STORE"/* "$3/" ;;
esac
""".replace("{digest}", DIGEST)

# `gh attestation verify` passes when ATTESTED is set.
GH = """#!/bin/sh
case "$1 $2" in
  "attestation verify") echo "$*" >> "$LOG/gh"; [ -n "$ATTESTED" ] ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("just", JUST), ("oras", ORAS), ("gh", GH)):
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    for d in ("store", "log", "home/.cache", "mnt-buildstream"):
        (tmp_path / d).mkdir(parents=True)
    # As on the CI runner: the BuildStream cache is a symlink to /mnt.
    (tmp_path / "home" / ".cache" / "buildstream").symlink_to(tmp_path / "mnt-buildstream")
    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "STORE": str(tmp_path / "store"),
        "LOG": str(tmp_path / "log"),
        "GRAPH": "freedesktop-sdk.bst:components/linux.bst bluefin-server/keys/linux-module-cert.bst",
        "EXISTS": "",
        "ATTESTED": "1",
        "GITHUB_REPOSITORY": "x/server",
    }
    env.pop("GITHUB_OUTPUT", None)
    return env


def run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], env=env, capture_output=True, text=True)


def test_seed_refuses_a_graph_that_reaches_the_keys(env: dict[str, str]) -> None:
    env["GRAPH"] += " bluefin-server/keys/boot-keys.bst"
    result = run(env, "seed", "ghcr.io/x/cache")
    assert result.returncode != 0
    assert not (Path(env["LOG"]) / "built").exists()
    assert not (Path(env["LOG"]) / "pushed").exists()


def test_seed_skips_an_existing_tag(env: dict[str, str]) -> None:
    env["EXISTS"] = "1"
    result = run(env, "seed", "ghcr.io/x/cache")
    assert result.returncode == 0
    assert not (Path(env["LOG"]) / "built").exists()
    assert "already exists and is attested" in result.stdout


def test_seed_replaces_an_existing_tag_without_an_attestation(zstd: str, env: dict[str, str]) -> None:
    env["EXISTS"] = "1"
    env["ATTESTED"] = ""
    result = run(env, "seed", "ghcr.io/x/cache")
    assert result.returncode == 0, result.stderr
    assert "exists without an attestation" in result.stdout
    assert (Path(env["LOG"]) / "built").exists()
    assert (Path(env["LOG"]) / "pushed").exists()


def test_seed_hands_the_pushed_digest_to_the_workflow(zstd: str, env: dict[str, str], tmp_path: Path) -> None:
    output = tmp_path / "github-output"
    env["GITHUB_OUTPUT"] = str(output)
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    assert output.read_text(encoding="utf-8").splitlines() == ["name=ghcr.io/x/cache", f"digest={DIGEST}"]


def test_seed_verifies_against_this_repositorys_build_workflow_on_main(env: dict[str, str]) -> None:
    env["EXISTS"] = "1"
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    (call,) = (Path(env["LOG"]) / "gh").read_text(encoding="utf-8").splitlines()
    args = call.split()
    assert f"oci://ghcr.io/x/cache@{DIGEST}" in args
    assert args[args.index("--repo") + 1] == "x/server"
    assert args[args.index("--signer-workflow") + 1] == "x/server/.github/workflows/build.yml"
    assert args[args.index("--source-ref") + 1] == "refs/heads/main"


def test_restore_miss_is_not_an_error(env: dict[str, str]) -> None:
    result = run(env, "restore", "ghcr.io/x/cache")
    assert result.returncode == 0
    assert "not available or not attested" in result.stdout
    assert not any((Path(env["HOME"]) / ".cache" / "buildstream").iterdir())
    assert not (Path(env["LOG"]) / "gh").exists()


def test_restore_refuses_a_tag_without_an_attestation(zstd: str, env: dict[str, str], tmp_path: Path) -> None:
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    fresh = tmp_path / "fresh-home"
    fresh.mkdir()
    env["HOME"] = str(fresh)
    env["ATTESTED"] = ""
    result = run(env, "restore", "ghcr.io/x/cache")
    assert result.returncode == 0
    assert "not available or not attested" in result.stdout
    assert not (fresh / ".cache" / "buildstream" / "cas").exists()
    oras_calls = (Path(env["LOG"]) / "oras").read_text(encoding="utf-8").splitlines()
    assert not any(call.startswith("pull") for call in oras_calls)


def test_restore_pulls_the_attested_digest_not_the_tag(zstd: str, env: dict[str, str], tmp_path: Path) -> None:
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    fresh = tmp_path / "fresh-home"
    fresh.mkdir()
    env["HOME"] = str(fresh)
    assert run(env, "restore", "ghcr.io/x/cache").returncode == 0
    oras_calls = (Path(env["LOG"]) / "oras").read_text(encoding="utf-8").splitlines()
    (pull,) = [call for call in oras_calls if call.startswith("pull")]
    assert pull.split()[-1] == f"ghcr.io/x/cache@{DIGEST}"


def test_restore_leaves_the_cache_untouched_on_a_corrupt_download(zstd: str, env: dict[str, str]) -> None:
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    cache = Path(env["HOME"]) / ".cache" / "buildstream"
    for entry in cache.iterdir():
        subprocess.run(["rm", "-rf", str(entry)], check=True)
    part = next(Path(env["STORE"]).iterdir())
    data = bytearray(part.read_bytes())
    data[len(data) // 2] ^= 0xFF
    part.write_bytes(bytes(data))
    result = run(env, "restore", "ghcr.io/x/cache")
    assert result.returncode == 0
    assert "did not verify" in result.stdout
    assert not any(cache.iterdir())


def test_seeded_cache_restores_into_an_empty_cache(zstd: str, env: dict[str, str], tmp_path: Path) -> None:
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    fresh = tmp_path / "fresh-home"
    fresh.mkdir()
    env["HOME"] = str(fresh)
    assert run(env, "restore", "ghcr.io/x/cache").returncode == 0
    cache = fresh / ".cache" / "buildstream"
    assert (cache / "cas" / "obj").read_text() == "kernel"
    assert not (cache / "logs").exists()

