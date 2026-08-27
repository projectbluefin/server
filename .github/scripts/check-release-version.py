#!/usr/bin/env python3
"""Enforce the release-version invariant for Bluefin Server.

project.conf declares:

    variables:
      release-version: "X.Y.Z"   # must match the FSDK point release

That value names every published release asset
(`bluefin-server-ddi-<v>.raw.zst`, `bluefin-server-<v>.efi`,
`bluefin-server-installer-<v>.raw.zst`, `k3s-<v>.raw.zst`) and is the
version systemd-sysupdate extracts from those filenames via `@v`.

The release *tag* is derived independently by the Justfile
(`fsdk_version`), which greps the point release out of the pinned
`elements/freedesktop-sdk.bst` junction ref. Renovate bumps that ref
automatically; nothing bumps `release-version`. When the two drift, CI
publishes a new tag containing assets that still carry the old version
string, so `systemd-sysupdate` sees no version change and the fleet
silently stops updating.

This script fails closed on that drift.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONF = ROOT / "project.conf"
FSDK_JUNCTION = ROOT / "elements" / "freedesktop-sdk.bst"

RELEASE_VERSION_RE = re.compile(
    r"^\s*release-version:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", re.MULTILINE
)
FSDK_REF_RE = re.compile(r"freedesktop-sdk-([0-9]+\.[0-9]+\.[0-9]+)")


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def main():
    conf = read(PROJECT_CONF)
    junction = read(FSDK_JUNCTION)

    conf_match = RELEASE_VERSION_RE.search(conf)
    if not conf_match:
        sys.exit(
            "ERROR: project.conf does not declare a "
            "'release-version: X.Y.Z' variable."
        )
    declared = conf_match.group(1)

    ref_match = FSDK_REF_RE.search(junction)
    if not ref_match:
        sys.exit(
            "ERROR: elements/freedesktop-sdk.bst has no "
            "'freedesktop-sdk-X.Y.Z' point release in its ref."
        )
    pinned = ref_match.group(1)

    if declared != pinned:
        sys.exit(
            "ERROR: release-version drift.\n"
            f"  project.conf release-version          : {declared}\n"
            f"  elements/freedesktop-sdk.bst pinned ref: {pinned}\n"
            "\n"
            "The release tag is derived from the junction ref while asset\n"
            "filenames are derived from release-version. While these differ,\n"
            "a new GitHub Release publishes assets still named with the old\n"
            "version, systemd-sysupdate reads the old version from '@v', and\n"
            "deployed hosts never see an update.\n"
            "\n"
            f"Fix: set release-version to \"{pinned}\" in project.conf."
        )

    print(f"OK: release-version {declared} matches the pinned FSDK point release.")


if __name__ == "__main__":
    main()
