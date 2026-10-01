#!/usr/bin/env python3
"""Decide whether a pull request needs the image build and boot test.

Reads the PR's changed paths (one per line, renames listed under both names)
on stdin and prints ``true`` or ``false`` for the build workflow's `changes`
job, which runs this script from the PR's base revision. Only changes that
cannot reach the image set or the boot test skip the ~2 h build: docs,
Markdown outside the build inputs, unit/e2e tests and the workflows that run
them. Anything else, and anything under a build input root, builds; so does
any change to this classifier or to the build workflow, and an empty or
truncated list.
"""

import sys

# The gate itself: a change to either must be built and boot-tested before
# the base branch's classifier trusts it.
GATE_FILES = frozenset(
    {
        ".github/scripts/image-build-needed.py",
        ".github/workflows/build.yml",
    }
)

# Paths the build or the boot test consume. Always build, even for *.md.
BUILD_PREFIXES = (
    "elements/",
    "files/",
    "include/",
    "patches/",
    "plugins/",
    "scripts/",
    "tests/fixtures/",
)

SKIP_PREFIXES = (
    "docs/",
    "tests/unit/",
    "tests/e2e/",
)

SKIP_FILES = frozenset(
    {
        ".github/scripts/docs-checks.py",
        ".github/workflows/docs-checks.yml",
        ".github/workflows/unit-tests.yml",
        ".github/workflows/track-junctions.yml",
        ".pre-commit-config.yaml",
        "cliff.toml",
        "LICENSE",
    }
)

# GitHub's "list pull request files" API stops at 3000 files.
API_FILE_LIMIT = 3000


def needs_build(path: str) -> bool:
    if path in GATE_FILES or path.startswith(BUILD_PREFIXES):
        return True
    if path.startswith(SKIP_PREFIXES) or path in SKIP_FILES or path.endswith(".md"):
        return False
    return True


def image_build_needed(paths: list[str]) -> bool:
    if not paths or len(paths) >= API_FILE_LIMIT:
        return True
    return any(needs_build(p) for p in paths)


def main() -> int:
    paths = [line.strip() for line in sys.stdin if line.strip()]
    print("true" if image_build_needed(paths) else "false")
    return 0


if __name__ == "__main__":
    sys.exit(main())
