"""A staging-only `kind: manual` element must disable the binary stripper.

FSDK's `manual` element runs default `strip-commands` after install. Those
commands shell out to `freedesktop-sdk-stripper`, a tool that arrives in the
sandbox with the FSDK build-system stacks — not with `base/base-stack.bst`.

An element that only copies files into `%{install-root}` therefore has nothing
to strip *and* no stripper to run it, so the default turns a no-op into
`sh: freedesktop-sdk-stripper: command not found` and the build dies with
exit 127. The repository's answer is `variables: strip-binaries: ""`.

`just validate` cannot catch this. It runs `bst show --deps all`, which
resolves the graph without executing a single build command, so a missing
`strip-binaries` override shows up only after a full `bst build` — eight
minutes into CI, and only for whoever pushes next.

That is not hypothetical: `os-cluster-bootstrap.bst` and
`os-cluster-manifests.bst` both shipped without the override and both failed
at exit 127 in the `Build DDI artifacts` run for the Kubernetes cutover, after
`just validate` had passed clean.

The discriminator is `config.build-commands`. An element that declares build
commands ran a compiler, so it has real ELF output and wants the stripper —
`uutils-coreutils.bst` is the one such element here, and it correctly leaves
the default alone. An element with no build commands only stages, and must
opt out.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
ELEMENTS_DIR = ROOT / "elements"


def _manual_elements():
    for path in sorted(ELEMENTS_DIR.glob("**/*.bst")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if data.get("kind") == "manual":
            yield path, data


STAGING_ONLY = [
    (path, data)
    for path, data in _manual_elements()
    if not (data.get("config") or {}).get("build-commands")
]

COMPILING = [
    (path, data)
    for path, data in _manual_elements()
    if (data.get("config") or {}).get("build-commands")
]


@pytest.mark.parametrize(
    "path,data", STAGING_ONLY, ids=[p.relative_to(ROOT).as_posix() for p, _ in STAGING_ONLY]
)
def test_staging_only_manual_elements_disable_the_stripper(path: Path, data: dict) -> None:
    strip = (data.get("variables") or {}).get("strip-binaries", None)

    assert strip == "", (
        f"{path.relative_to(ROOT)} is a kind: manual element with no "
        f"config.build-commands, so it only stages files and no stripper is in "
        f"its sandbox. It must set:\n\n"
        f"    variables:\n"
        f"      strip-binaries: \"\"\n\n"
        f"Without it the build fails with "
        f"'freedesktop-sdk-stripper: command not found' (exit 127), which "
        f"`just validate` cannot detect because it never runs a build command. "
        f"Got strip-binaries={strip!r}."
    )


def test_compiling_manual_elements_keep_the_default_stripper() -> None:
    # Guards the discriminator itself: if this list empties, the rule above has
    # silently become unconditional and stops distinguishing anything.
    assert COMPILING, (
        "no kind: manual element declares config.build-commands; the "
        "staging-only rule above is no longer discriminating and its "
        "build-commands check needs re-deriving"
    )

    for path, data in COMPILING:
        strip = (data.get("variables") or {}).get("strip-binaries", None)
        assert strip != "", (
            f"{path.relative_to(ROOT)} compiles (config.build-commands is set) "
            f"but disables the stripper, so its binaries ship unstripped. "
            f"Remove the strip-binaries override or move the build commands out."
        )


def test_at_least_one_manual_element_is_discovered() -> None:
    # Guards the parser: a glob or kind-key regression would make the
    # parametrized test above vacuously pass with zero cases.
    assert STAGING_ONLY, (
        "no staging-only kind: manual elements found under elements/ — the "
        "discovery in this module has regressed"
    )
