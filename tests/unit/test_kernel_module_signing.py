"""bluefin-server/kernel-modules.bst signs and compresses every module, in parallel.

Runs the element's signing step against stub sign-file, zstd, modinfo and
openssl: every module, whether shipped as .ko or .ko.zst, must come out signed
and compressed, and one failing worker must fail the step.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENT = ROOT / "elements" / "bluefin-server" / "kernel-modules.bst"
INDEP_LIBDIR = "/usr/lib"

STUBS = {
    "openssl": 'while [ $# -gt 0 ]; do [ "$1" = -out ] && : > "$2"; shift; done\n',
    "sign-file": 'f="$4"; case "$f" in */bad.ko) exit 1;; esac; printf "+sig" >> "$f"\n',
    "modinfo": 'grep -q "+sig$" "$3" && echo sha512\n',
    "zstd": (
        'if [ "$1" = -d ]; then f="$4"; mv "$f" "${f%.zst}"; '
        'else [ "$1" = -19 ] || exit 1; f="$4"; mv "$f" "$f.zst"; fi\n'
    ),
}


def signing_step() -> str:
    commands = yaml.safe_load(ELEMENT.read_text(encoding="utf-8"))["config"]["install-commands"]
    (step,) = [c for c in commands if "sign-file" in c]
    return step


def run(tmp_path: Path, modules: dict[str, str]) -> subprocess.CompletedProcess:
    root = tmp_path / "root"
    moddir = root / INDEP_LIBDIR.lstrip("/") / "modules" / "6.0.0"
    for name, content in modules.items():
        (moddir / name).parent.mkdir(parents=True, exist_ok=True)
        (moddir / name).write_text(content, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    for name, body in STUBS.items():
        (bindir / name).write_text("#!/bin/sh\n" + body, encoding="utf-8")
        (bindir / name).chmod(0o755)
    script = signing_step().replace("%{install-root}", str(root)).replace("%{indep-libdir}", INDEP_LIBDIR)
    assert "%{" not in script
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    return subprocess.run(["bash", "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True)


def test_every_module_is_signed_then_compressed(tmp_path: Path) -> None:
    modules = {f"kernel/drivers/m{i}.ko{'.zst' if i % 2 else ''}": f"m{i}" for i in range(40)}
    result = run(tmp_path, modules)
    assert result.returncode == 0, result.stderr
    moddir = tmp_path / "root" / INDEP_LIBDIR.lstrip("/") / "modules" / "6.0.0"
    out = sorted(p.relative_to(moddir).as_posix() for p in moddir.rglob("*") if p.is_file())
    assert out == sorted(f"kernel/drivers/m{i}.ko.zst" for i in range(40))
    for i in range(40):
        assert (moddir / f"kernel/drivers/m{i}.ko.zst").read_text(encoding="utf-8") == f"m{i}+sig"


def test_one_failing_module_fails_the_step(tmp_path: Path) -> None:
    modules = {f"kernel/m{i}.ko": "x" for i in range(20)}
    modules["kernel/bad.ko.zst"] = "x"
    result = run(tmp_path, modules)
    assert result.returncode != 0
