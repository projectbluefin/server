"""Drift gate: every path under ``files/`` is image payload or declared host tooling.

``files/`` is the repository's image-payload tree. A file only reaches an image
if some element stages it with a ``kind: local`` source, e.g.::

    sources:
      - kind: local
        path: files/os/sysupdate.d

Nothing else pulls ``files/`` into the build graph, so a directory that no
element names is invisible to ``just validate`` (which only runs
``bst show --deps all`` on the three OCI targets) and to the image build. It is
also invisible to the unit suite, because bats tests execute helper scripts
straight out of the checkout whether or not they ship.

This module enforces both directions of the contract:

* every ``path:`` an element declares still exists on disk, so renaming a
  payload directory cannot silently drop it out of the image; and
* every file under ``files/`` is staged, or is declared host-side tooling, or is
  an explicitly recorded waiver.

Staging is matched by declaration, not by graph reachability: a path named by an
element that no OCI target depends on still counts as staged here.

``KNOWN_UNSTAGED`` is shrink-only: staging a waived path fails the gate until
the waiver is deleted, so the record cannot outlive the bug it describes.
"""

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS_DIR = ROOT / "elements"
FILES_DIR = ROOT / "files"

# Paths under files/ that are host-side tooling, executed from a repository
# checkout and deliberately absent from every image.
HOST_TOOLING = {
    # Host developer CLI: Justfile `install-vm` and
    # scripts/lima-e2e-kubestellar-test.sh run it from the checkout.
    "files/bin/bluefin-kubestellar",
    # limactl VM template consumed by Justfile `test-e2e-lima`.
    "files/lima",
    # Release public key; CI copies it to files/boot-keys/import-pubring.pgp,
    # from where bluefin-server/os-sysupdate-keys.bst installs it.
    "files/os/sysupdate-keys/import-pubring.gpg",
    # Release module certificate; CI copies it to
    # files/boot-keys/modules/linux-module-cert.crt for the kernel cache
    # (scripts/kernel-cache.sh), from where the kernel's
    # linux-module-cert override stages it.
    "files/release-keys/linux-module-cert.crt",
}

# Gitignored signing material, absent from every fresh checkout:
# scripts/gen-dev-keys.sh writes it for local and pull-request builds and CI
# installs the project keys there on main. Elements staging paths under it are
# checked against the generator instead of the working tree.
GENERATED_KEY_DIR = "files/boot-keys"
KEY_GENERATOR = ROOT / "scripts" / "gen-dev-keys.sh"

# Payload that claims to ship but is staged by no element. Each entry must name
# the issue tracking its resolution. Shrink this set; never grow it.
KNOWN_UNSTAGED = set()


def _element_files():
    return sorted(ELEMENTS_DIR.rglob("*.bst"))


def _local_source_paths(document):
    """Yield every ``path:`` of a ``kind: local`` source in a parsed element."""
    if not isinstance(document, dict):
        return
    for source in document.get("sources") or []:
        if isinstance(source, dict) and source.get("kind") == "local":
            path = source.get("path")
            if isinstance(path, str):
                yield path


def _declared_paths():
    """Map each declared ``kind: local`` path to the elements declaring it."""
    declared = {}
    for element in _element_files():
        document = yaml.safe_load(element.read_text())
        for path in _local_source_paths(document):
            rel = element.relative_to(ROOT).as_posix()
            declared.setdefault(path.rstrip("/"), []).append(rel)
    return declared


def _staged_paths():
    """Declared paths that live under ``files/``, as repo-relative strings."""
    return {path for path in _declared_paths() if path == "files" or path.startswith("files/")}


def _is_staged(rel_path, staged):
    """True when ``rel_path`` is a declared path or sits under one."""
    candidate = Path(rel_path)
    return any(
        candidate == Path(path) or Path(path) in candidate.parents for path in staged
    )


def _is_host_tooling(rel_path):
    candidate = Path(rel_path)
    return any(
        candidate == Path(path) or Path(path) in candidate.parents
        for path in HOST_TOOLING
    )


def _payload_files():
    return sorted(
        p.relative_to(ROOT).as_posix() for p in FILES_DIR.rglob("*") if p.is_file()
    )


def test_at_least_one_element_stages_payload():
    """Guards the gate itself: a parser regression must not silently pass."""
    staged = _staged_paths()
    assert staged, (
        "no element declares a kind: local source under files/ — either the "
        "payload wiring was removed or this gate stopped parsing elements"
    )


def _is_generated_key_path(path):
    return path == GENERATED_KEY_DIR or path.startswith(GENERATED_KEY_DIR + "/")


@pytest.mark.parametrize(
    "declared", sorted(p for p in _declared_paths() if not _is_generated_key_path(p))
)
def test_declared_source_paths_exist(declared):
    """A stale ``path:`` silently drops payload out of the image."""
    owners = ", ".join(_declared_paths()[declared])
    assert (ROOT / declared).exists(), (
        f"{owners} declares a kind: local source path that does not exist: "
        f"{declared}. Renaming payload requires updating the element that "
        f"stages it."
    )


@pytest.mark.parametrize(
    "declared", sorted(p for p in _declared_paths() if _is_generated_key_path(p))
)
def test_declared_key_paths_are_generated(declared):
    """Key paths are never committed; the dev-key generator must produce them."""
    owners = ", ".join(_declared_paths()[declared])
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert GENERATED_KEY_DIR + "/" in ignored, f"{GENERATED_KEY_DIR}/ must stay gitignored"
    generator = KEY_GENERATOR.read_text(encoding="utf-8")
    assert f'/{GENERATED_KEY_DIR}"' in generator, (
        f"{KEY_GENERATOR.name} no longer writes {GENERATED_KEY_DIR}"
    )
    entry = declared[len(GENERATED_KEY_DIR):].lstrip("/")
    assert not entry or f'"${{dir}}/{entry}"' in generator, (
        f"{owners} stages {declared}, which {KEY_GENERATOR.name} does not "
        f"produce. Renaming key material requires updating the generator and "
        f"the element that stages it."
    )


def test_every_payload_file_is_staged_or_declared():
    """No file under files/ may be unreachable without an explicit declaration."""
    staged = _staged_paths()
    orphans = [
        rel
        for rel in _payload_files()
        if not _is_staged(rel, staged)
        and not _is_host_tooling(rel)
        and rel not in KNOWN_UNSTAGED
    ]
    assert not orphans, (
        "files/ paths reach no image and are not declared host tooling:\n  "
        + "\n  ".join(orphans)
        + "\n\nStage them with a kind: local source on an element that "
        "os-stack.bst, an initrd stack, or an oci/ target depends on; or "
        "add them to HOST_TOOLING if they are host-side only."
    )


def test_host_tooling_declarations_are_not_stale():
    staged = _staged_paths()
    for declared in sorted(HOST_TOOLING):
        assert (ROOT / declared).exists(), (
            f"HOST_TOOLING names {declared}, which no longer exists — drop the "
            f"declaration."
        )
        assert not _is_staged(declared, staged), (
            f"{declared} is declared host tooling but an element now stages it "
            f"into an image. Remove it from HOST_TOOLING."
        )


def test_known_unstaged_waivers_are_still_unstaged():
    """Shrink-only: a waiver must be deleted once the path actually ships."""
    staged = _staged_paths()
    for waived in sorted(KNOWN_UNSTAGED):
        assert (ROOT / waived).exists(), (
            f"KNOWN_UNSTAGED names {waived}, which no longer exists — drop the "
            f"waiver."
        )
        assert not _is_staged(waived, staged), (
            f"{waived} is now staged by an element. Remove it from "
            f"KNOWN_UNSTAGED so the gate protects it."
        )
