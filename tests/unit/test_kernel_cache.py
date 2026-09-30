"""scripts/kernel-cache.sh: the public ghcr.io kernel cache.

The pushed tarball is public, so `seed` must refuse whenever the graph it
builds reaches the element that stages private keys; `restore` must never fail
a release build; and what `seed` packs must come back byte for byte in an
empty cache directory. `just` and `oras` are stubbed; tar, zstd and split are
real.
"""

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "kernel-cache.sh"
KEYS = ["a" * 64, "b" * 64]

JUST = """#!/bin/sh
case "$*" in
  *"--deps none"*) printf '%s\\n' {keys} ;;
  *"--deps all"*) printf '%s\\n' $GRAPH ;;
  "bst build"*) echo "$*" >> "$LOG/built"; mkdir -p "$HOME/.cache/buildstream/cas" "$HOME/.cache/buildstream/logs";
                printf 'kernel' > "$HOME/.cache/buildstream/cas/obj"; printf 'log' > "$HOME/.cache/buildstream/logs/l" ;;
esac
""".replace("{keys}", " ".join(KEYS))

ORAS = """#!/bin/sh
case "$1 $2" in
  "manifest fetch") [ -n "$EXISTS" ] ;;
  "push "*) shift; while [ "${1#-}" != "$1" ]; do shift 2; done; shift; cp "$@" "$STORE/"; echo push >> "$LOG/pushed" ;;
  "pull -o") [ -n "$(ls "$STORE")" ] && cp "$STORE"/* "$3/" ;;
esac
"""


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in (("just", JUST), ("oras", ORAS)):
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    for d in ("store", "log", "home/.cache", "mnt-buildstream"):
        (tmp_path / d).mkdir(parents=True)
    # As on the CI runner: the BuildStream cache is a symlink to /mnt.
    (tmp_path / "home" / ".cache" / "buildstream").symlink_to(tmp_path / "mnt-buildstream")
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "HOME": str(tmp_path / "home"),
        "STORE": str(tmp_path / "store"),
        "LOG": str(tmp_path / "log"),
        "GRAPH": "freedesktop-sdk.bst:components/linux.bst bluefin-server/keys/linux-module-cert.bst",
        "EXISTS": "",
    }


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
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    assert not (Path(env["LOG"]) / "built").exists()


def test_restore_miss_is_not_an_error(env: dict[str, str]) -> None:
    result = run(env, "restore", "ghcr.io/x/cache")
    assert result.returncode == 0
    assert "not available" in result.stdout
    assert not any((Path(env["HOME"]) / ".cache" / "buildstream").iterdir())


def test_seeded_cache_restores_into_an_empty_cache(env: dict[str, str], tmp_path: Path) -> None:
    assert run(env, "seed", "ghcr.io/x/cache").returncode == 0
    fresh = tmp_path / "fresh-home"
    fresh.mkdir()
    env["HOME"] = str(fresh)
    assert run(env, "restore", "ghcr.io/x/cache").returncode == 0
    cache = fresh / ".cache" / "buildstream"
    assert (cache / "cas" / "obj").read_text() == "kernel"
    assert not (cache / "logs").exists()

