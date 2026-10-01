#!/usr/bin/env python3
"""Prepare a host stock baseline; optionally acquire actual disposable cache proof.

BuildStream generates its own platform artifact from tracked sources. This command
never builds upstream components or bootstraps a real cluster. --verify is explicit
and requires a local container provider; ordinary preparation needs Python and Git.
"""
import argparse
import ctypes
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import uuid

REPO = Path(__file__).resolve().parent.parent
MARKER = ".bluefin-generated.json"
OWNER = "bluefin-server-prepare-v1"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode() + b"\n"


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def inventory(directory):
    result = {}
    for path in sorted(directory.rglob("*")):
        name = path.relative_to(directory).as_posix()
        if name == MARKER:
            continue
        if path.is_symlink():
            target = os.readlink(path)
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(directory.resolve()):
                raise ValueError("generated artifact symlink escapes import: " + name)
            result[name] = {"symlink": target}
        elif path.is_file():
            result[name] = {"sha256": digest(path), "mode": path.stat().st_mode & 0o777}
        elif not path.is_dir():
            raise ValueError("unsupported generated artifact: " + name)
    return result


def seal(directory, inputs):
    (directory / MARKER).write_bytes(canonical({"owner": OWNER, "inputs": inputs,
                                               "files": inventory(directory)}))


def reusable(directory, inputs):
    try:
        marker = json.loads((directory / MARKER).read_text())
        return isinstance(marker, dict) and marker.get("owner") == OWNER and marker.get("inputs") == inputs and marker.get("files") == inventory(directory)
    except (OSError, ValueError):
        return False


def owned_generation(destination):
    if destination.is_symlink() or not destination.is_dir():
        return False
    try:
        marker_path = destination / MARKER
        if marker_path.is_symlink():
            return False
        marker = json.loads(marker_path.read_text())
        return isinstance(marker, dict) and marker.get("owner") == OWNER
    except (OSError, ValueError):
        return False


def publish(generation, destination):
    generation, destination = Path(generation), Path(destination)
    root = (destination.parent / ".generations").resolve(strict=True)
    if generation.is_symlink() or not generation.resolve(strict=True).is_relative_to(root):
        raise ValueError("generation outside owned host baseline store")
    exists = os.path.lexists(destination)
    if exists and not owned_generation(destination):
        raise ValueError("refusing to replace unowned host baseline: " + str(destination))
    try:
        marker = json.loads((generation / MARKER).read_text())
    except (OSError, ValueError) as error:
        raise ValueError("refusing unsealed host baseline") from error
    if not isinstance(marker, dict) or marker.get("owner") != OWNER or not isinstance(marker.get("files"), dict):
        raise ValueError("refusing unsealed host baseline")
    if not reusable(generation, marker.get("inputs")):
        raise ValueError("refusing modified host baseline")
    if exists:
        # renameat2 RENAME_EXCHANGE is one atomic filesystem operation: the new
        # complete directory becomes the selected host baseline, and the old owned
        # directory remains at the candidate's .generations location. A failed
        # exchange or interruption cannot expose an absent or half-built root.
        libc = ctypes.CDLL(None, use_errno=True)
        exchange = getattr(libc, "renameat2", None)
        if exchange is None:
            raise OSError("atomic real-directory publication requires Linux renameat2")
        exchange.argtypes = (ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint)
        exchange.restype = ctypes.c_int
        if exchange(-100, os.fsencode(generation), -100, os.fsencode(destination), 2) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(destination))
    else:
        os.rename(generation, destination)
    # Persist both exchanged names; no deletion or copy fallback can damage a
    # user's output or silently weaken the real-root/atomic publication contract.
    for parent in {generation.parent, destination.parent}:
        descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def tree_inputs(paths):
    files = {}
    for base in paths:
        candidates = sorted(base.rglob("*")) if base.is_dir() else [base]
        for path in candidates:
            if path.is_symlink():
                raise ValueError("build input may not be a symlink: " + str(path))
            if path.is_file() and "__pycache__" not in path.parts:
                if base.name == "manifests" and "tests" in path.relative_to(base).parts:
                    continue
                files[path.relative_to(REPO).as_posix()] = digest(path)
    return hashlib.sha256(canonical(files)).hexdigest()


def run(*arguments):
    print("+ " + " ".join(map(str, arguments)), flush=True)
    subprocess.run(list(map(str, arguments)), cwd=REPO, check=True)


def generation(parent):
    store = parent / ".generations"
    if store.is_symlink():
        raise ValueError("generation store must not be a symlink")
    store.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix="prepare-", dir=store))


def architecture(value=None):
    value = value or os.environ.get("BST_ARCH") or platform.machine()
    aliases = {"x86_64": "amd64", "amd64": "amd64", "aarch64": "arm64", "arm64": "arm64"}
    if value not in aliases:
        raise ValueError("unsupported build architecture: " + value)
    return aliases[value]


def prepare(args):
    cache = REPO / ".cache"
    cache.mkdir(exist_ok=True)
    lock_fd = os.open(cache / ".prepare-server.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock_fd, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        arch = architecture(args.architecture)
        platform_parent = cache / "platform"
        platform_parent.mkdir(exist_ok=True)
        destination = platform_parent / arch
        inputs = tree_inputs([REPO / "files/server/manifests"])
        if not (owned_generation(destination) and reusable(destination, inputs)):
            if os.path.lexists(destination) and not owned_generation(destination):
                raise ValueError("refusing unowned platform output: " + str(destination))
            output = generation(platform_parent) / "platform"
            run(sys.executable, REPO / "files/server/manifests/produce-baseline.py", "--output", output)
            seal(output, inputs)
            publish(output, destination)
        result = {"platform": str(destination), "baseline_commit": (destination / "baseline-commit").read_text().strip()}
        if args.verify:
            spec = importlib.util.spec_from_file_location("server_platform_verifier", REPO / "scripts/verify-server-platform.py")
            verifier = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(verifier)
            identity = verifier.proof_identity(destination)
            proofs = cache / "server-proofs"
            proofs.mkdir(exist_ok=True)
            proof = proofs / (hashlib.sha256(canonical(identity)).hexdigest() + ".json")
            try:
                matched = verifier.matching_proof(json.loads(proof.read_text()), identity)
            except (OSError, ValueError):
                matched = False
            if not matched:
                workspace = generation(platform_parent)
                fresh_proof = workspace / "observed-proof.json"
                run(sys.executable, REPO / "scripts/verify-server-platform.py", "--staged", destination,
                    "--output", fresh_proof, "--artifacts", proofs / ("run-" + uuid.uuid4().hex),
                    "--cache", cache / "server-proof-tools", "--provider", args.provider)
                if proof.is_symlink():
                    raise ValueError("proof cache record must not be a symlink")
                os.replace(fresh_proof, proof)
            if not verifier.matching_proof(json.loads(proof.read_text()), identity):
                raise ValueError("disposable observations do not cover current stock inputs")
            result["proof"] = str(proof)
        print(json.dumps(result))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--architecture", choices=("amd64", "arm64", "x86_64", "aarch64"))
    parser.add_argument("--verify", action="store_true", help="run/reuse evidence-bound local disposable Argo CD/Valkey proof")
    parser.add_argument("--provider", choices=("podman", "docker"), default="podman")
    args = parser.parse_args()
    try:
        prepare(args)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"prepare-server: {error}\n")


if __name__ == "__main__":
    main()
