#!/usr/bin/env python3
"""Enforce the FSDK version invariant for Bluefin Server.

project.conf declares `installer-version: "X.Y.Z"`, the freedesktop-sdk point
release every OS element composes from. It must match the ref pinned in
elements/freedesktop-sdk.bst.

The image version (include/image.yml, %{image-version}) is a separate,
per-build axis set by `just set-version`; systemd-sysupdate extracts it from
release asset names via `@v`. The k0s and OpenZFS sysexts pin their own
upstream versions in include/k0s.yml and include/zfs.yml.

This script fails closed on drift.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONF = ROOT / "project.conf"
FSDK_JUNCTION = ROOT / "elements" / "freedesktop-sdk.bst"

INSTALLER_VERSION_RE = re.compile(
    r"^\s*installer-version:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", re.MULTILINE
)
FSDK_REF_RE = re.compile(r"freedesktop-sdk-([0-9]+\.[0-9]+\.[0-9]+)")


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def main():
    conf = read(PROJECT_CONF)
    junction = read(FSDK_JUNCTION)

    installer_match = INSTALLER_VERSION_RE.search(conf)
    if not installer_match:
        sys.exit(
            "ERROR: project.conf does not declare an "
            "'installer-version: X.Y.Z' variable."
        )
    installer_declared = installer_match.group(1)

    fsdk_match = FSDK_REF_RE.search(junction)
    if not fsdk_match:
        sys.exit(
            "ERROR: elements/freedesktop-sdk.bst has no "
            "'freedesktop-sdk-X.Y.Z' point release in its ref."
        )
    fsdk_pinned = fsdk_match.group(1)

    if installer_declared != fsdk_pinned:
        sys.exit(
            "ERROR: installer-version drift.\n"
            f"  project.conf installer-version        : {installer_declared}\n"
            f"  elements/freedesktop-sdk.bst pinned ref: {fsdk_pinned}\n"
            "\n"
            "The installer release tag and installer assets are derived from the\n"
            "junction ref while project.conf declares installer-version.\n"
            "\n"
            f"Fix: set installer-version to \"{fsdk_pinned}\" in project.conf."
        )

    print(
        f"OK: installer-version {installer_declared} matches pinned FSDK point release."
    )


if __name__ == "__main__":
    main()
