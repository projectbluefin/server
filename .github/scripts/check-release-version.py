#!/usr/bin/env python3
"""Enforce the FSDK version invariant for Bluefin Server.

project.conf declares `installer-version: "X.Y.Z"`, the freedesktop-sdk point
release every OS element composes from. It must match the ref pinned in
elements/freedesktop-sdk.bst.

The image version (include/image.yml, %{image-version}) is a separate,
per-build axis set by `just set-version`; systemd-sysupdate extracts it from
release asset names via `@v`. The k0s and OpenZFS sysexts pin their own
upstream versions in include/k0s.yml and include/zfs.yml.

This script fails closed on drift. It is also the one parser of the pinned
FSDK point release:

  --print-fsdk  print it (the Justfile's fsdk_version)
  --fix         set installer-version to it, then check (track-junctions.yml)
"""

import argparse
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
# Any installer-version value, valid or not, for --fix to replace.
INSTALLER_LINE_RE = re.compile(r"^([ \t]*installer-version:[ \t]*).*$", re.MULTILINE)


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def pinned_fsdk_version():
    fsdk_match = FSDK_REF_RE.search(read(FSDK_JUNCTION))
    if not fsdk_match:
        sys.exit(
            "ERROR: elements/freedesktop-sdk.bst has no "
            "'freedesktop-sdk-X.Y.Z' point release in its ref."
        )
    return fsdk_match.group(1)


def fix_installer_version(fsdk_pinned):
    conf = read(PROJECT_CONF)
    fixed = INSTALLER_LINE_RE.sub(lambda m: f'{m.group(1)}"{fsdk_pinned}"', conf, count=1)
    if fixed != conf:
        PROJECT_CONF.write_text(fixed, encoding="utf-8")


def main(argv=()):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--print-fsdk", action="store_true", help="print the pinned FSDK point release")
    action.add_argument("--fix", action="store_true", help="sync installer-version to the pinned FSDK point release")
    args = parser.parse_args(argv)

    fsdk_pinned = pinned_fsdk_version()
    if args.print_fsdk:
        print(fsdk_pinned)
        return
    if args.fix:
        fix_installer_version(fsdk_pinned)

    conf = read(PROJECT_CONF)
    installer_match = INSTALLER_VERSION_RE.search(conf)
    if not installer_match:
        sys.exit(
            "ERROR: project.conf does not declare an "
            "'installer-version: X.Y.Z' variable."
        )
    installer_declared = installer_match.group(1)

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
    main(sys.argv[1:])
