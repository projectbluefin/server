#!/usr/bin/env python3
"""Enforce the release-version invariant for Bluefin Server.

The two release version axes are each declared in exactly one place:

    project.conf        installer-version: "X.Y.Z"  # FSDK point release
    include/flatcar.yml flatcar-version:   "X.Y.Z"  # Flatcar LTS release

The installer-version axis names the offline installer disk image and PXE boot
inputs (bluefin-server-installer-<v>.raw.zst, bluefin-server-pxe-*), which
compose their userspace from freedesktop-sdk.

The flatcar-version axis names the OS payload release assets
(bluefin-server-ddi-<v>.raw.zst, bluefin-server-<v>.efi) and is the version
systemd-sysupdate extracts from those filenames via `@v`. project.conf pulls
include/flatcar.yml in via its `(@)` list, so %{flatcar-version} resolves
project-wide without being restated.

The k0s sysext is on its own axis: an independently-pinned third-party
payload versioned from `include/k0s.yml` and enforced separately by
`.github/scripts/check-k0s-version.py`.

This script validates both axes against their pins:
  * project.conf installer-version against elements/freedesktop-sdk.bst
  * include/flatcar.yml flatcar-version is well-formed

This script fails closed on any drift.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT_CONF = ROOT / "project.conf"
FSDK_JUNCTION = ROOT / "elements" / "freedesktop-sdk.bst"
FLATCAR_PIN = ROOT / "include" / "flatcar.yml"

INSTALLER_VERSION_RE = re.compile(
    r"^\s*installer-version:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", re.MULTILINE
)
FSDK_REF_RE = re.compile(r"freedesktop-sdk-([0-9]+\.[0-9]+\.[0-9]+)")
FLATCAR_PIN_RE = re.compile(
    r"^\s*flatcar-version:\s*[\"']?([0-9]+\.[0-9]+\.[0-9]+)[\"']?\s*$", re.MULTILINE
)


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def main():
    conf = read(PROJECT_CONF)
    junction = read(FSDK_JUNCTION)
    flatcar = read(FLATCAR_PIN)

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

    flatcar_pin_match = FLATCAR_PIN_RE.search(flatcar)
    if not flatcar_pin_match:
        sys.exit(
            "ERROR: include/flatcar.yml does not declare a "
            "'flatcar-version: X.Y.Z' variable."
        )
    flatcar_pinned = flatcar_pin_match.group(1)

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
        f"OK: installer-version {installer_declared} matches pinned FSDK point release.\n"
        f"OK: flatcar-version {flatcar_pinned} declared in include/flatcar.yml."
    )


if __name__ == "__main__":
    main()
