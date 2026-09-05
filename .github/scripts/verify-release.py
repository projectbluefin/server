#!/usr/bin/env python3
"""Validate the exact artifact set assembled for a Bluefin Server release."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ARTIFACT_PATTERNS = (
    "bluefin-server-{version}.efi",
    "bluefin-server-ddi-{version}.raw.zst",
    "bluefin-server-ddi-{version}.spdx.json",
    "bluefin-server-installer-{version}.raw.zst",
    "bluefin-server-installer-{version}.spdx.json",
    "k3s-{version}.raw.zst",
    "k3s-{version}.spdx.json",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()

    if not re.fullmatch(r"\d+\.\d+\.\d+", args.version):
        parser.error(f"invalid release version: {args.version}")
    if not args.directory.is_dir():
        print(f"release directory does not exist: {args.directory}", file=sys.stderr)
        return 1

    expected = {pattern.format(version=args.version) for pattern in ARTIFACT_PATTERNS}
    actual = {path.name for path in args.directory.iterdir() if path.is_file()}
    unexpected = actual - expected
    missing = expected - actual
    if missing:
        print(f"missing release artifacts: {', '.join(sorted(missing))}", file=sys.stderr)
    if unexpected:
        print(f"unexpected release artifacts: {', '.join(sorted(unexpected))}", file=sys.stderr)
    if missing or unexpected:
        return 1

    print(f"release artifact set verified for {args.version}: {len(expected)} files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
