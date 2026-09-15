#!/usr/bin/env python3
"""Enforce the Flatcar single-source-of-truth invariant.

include/flatcar.yml is the ONLY place a Flatcar upstream version or sha256 is
declared. Every Flatcar element reads those values through %{...} variable
substitution (see elements/flatcar/*.bst); nothing restates a pin.

This script fails the build when a pinned literal — a Flatcar version, kernel
vermagic, or source sha256 — is hardcoded anywhere in elements/ or files/,
where it would drift from include/flatcar.yml and silently pull a different
upstream payload than the pin file names. It reads the declared pins out of
include/flatcar.yml and greps the tree for any copy of them outside that file,
in the spirit of check-release-version.py.
"""

import re
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIN_FILE = ROOT / "include" / "flatcar.yml"
SCAN_DIRS = (ROOT / "elements", ROOT / "files")

# A `key: "value"` / `key: 'value'` / `key: bare` line inside the variables:
# block of the pin file. The captured group is the declared pin literal.
VAR_RE = re.compile(
    r'^\s+[A-Za-z0-9_.-]+:\s*(?:"([^"]*)"|' r"'([^']*)'" r'|([^\s#]+))',
    re.MULTILINE,
)
# Directories that legitimately echo upstream digests and must never be scanned.
SKIP_DIRS = {".git", "__pycache__", "node_modules"}


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def declared_pins(pin_text):
    """Every literal declared in the variables: block of the pin file."""
    pins = []
    for value in VAR_RE.findall(pin_text):
        literal = next(part for part in value if part)
        if literal:
            pins.append(literal)
    return pins


def iter_scan_files():
    for scan_dir in SCAN_DIRS:
        if not scan_dir.is_dir():
            continue
        # os.walk with dir pruning so files under .git / __pycache__ /
        # node_modules are never read (rglob would flatten and scan them).
        for root, dirs, files in os.walk(scan_dir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for name in files:
                if name.endswith(".pyc"):
                    continue
                yield Path(root) / name


def is_binary(text):
    return "\x00" in text


def main():
    pins = declared_pins(read(PIN_FILE))
    if not pins:
        sys.exit(
            "ERROR: include/flatcar.yml declares no pins to enforce. Add the "
            "Flatcar version / sha256 variables here."
        )

    violations = []
    for path in iter_scan_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if is_binary(text):
            continue
        for pin in pins:
            if pin in text:
                violations.append((path.relative_to(ROOT), pin))

    if violations:
        lines = [
            "ERROR: Flatcar pin(s) hardcoded outside include/flatcar.yml.\n"
            "Every Flatcar version and sha256 must live in include/flatcar.yml "
            "and be\n"
            "referenced via %{...}; hardcoding one here lets it drift from the "
            "pin file.\n"
            "\nRemove the literal and read it from include/flatcar.yml:"
        ]
        for path, pin in violations:
            lines.append(f"  {path}: {pin}")
        sys.exit("\n".join(lines))

    print(f"OK: no Flatcar pins hardcoded outside include/flatcar.yml ({len(pins)} pinned).")


if __name__ == "__main__":
    main()
