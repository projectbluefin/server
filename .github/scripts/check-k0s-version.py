#!/usr/bin/env python3
"""Enforce the k0s version invariant for Bluefin Server.

k0s is an independently-pinned third-party payload, not an OS asset, so it is
versioned on its own axis. ``include/k0s.yml`` is the single source of truth:

    variables:
      k0s-k8s-version: "1.36.4"
      k0s-patch: "0"
      k0s-upstream-tag: "v%{k0s-k8s-version}%2Bk0s.%{k0s-patch}"
      k0s-version: "%{k0s-k8s-version}-k0s.%{k0s-patch}"

Three consumers restate that version in three different spellings, and all
three must move together or the sysext silently stops updating:

  * ``elements/k0s/k0s-bin.bst``          — the upstream download URL.
  * ``elements/oci/k0s-sysext.bst``       — the release asset filename, which
    ``files/os/sysupdate.d/70-k0s.transfer`` reads as the version oracle
    through its ``@v`` wildcard.
  * ``files/k0s/sysext/extension-release.k0s`` — the ``VERSION_ID=`` reported
    by ``systemd-sysext status``.

This script fails closed if any consumer reintroduces a literal k0s version or
drops back onto the OS release axis, and cross-checks that the derived asset
filename still matches the sysupdate transfer's MatchPattern.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K0S_INCLUDE = ROOT / "include" / "k0s.yml"
K0S_BIN = ROOT / "elements" / "k0s" / "k0s-bin.bst"
K0S_SYSEXT = ROOT / "elements" / "oci" / "k0s-sysext.bst"
EXTENSION_RELEASE = ROOT / "files" / "k0s" / "sysext" / "extension-release.k0s"
TRANSFER = ROOT / "files" / "os" / "sysupdate.d" / "70-k0s.transfer"

SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9._~^+-]+$")
LITERAL_VERSION_RE = re.compile(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:\+|%2B|-)k0s\.[0-9]+")


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def scalar(text, name, where):
    """Read a ``name: "value"`` scalar out of a BuildStream YAML fragment."""
    match = re.search(
        rf"^\s*{re.escape(name)}:\s*[\"']([^\"']+)[\"']\s*$", text, re.MULTILINE
    )
    if not match:
        sys.exit(f"ERROR: {where} does not declare a '{name}:' variable.")
    return match.group(1)


def expand(value, variables, where):
    """Resolve ``%{...}`` references the way BuildStream would."""
    for _ in range(len(variables) + 1):
        refs = re.findall(r"%\{([a-zA-Z][a-zA-Z0-9_-]*)\}", value)
        if not refs:
            return value
        for ref in refs:
            if ref not in variables:
                sys.exit(
                    f"ERROR: {where} references undefined variable '%{{{ref}}}'."
                )
            value = value.replace("%{" + ref + "}", variables[ref])
    sys.exit(f"ERROR: {where} has a circular variable reference: {value}")


def fail(problem, fix):
    sys.exit(f"ERROR: {problem}\n\nFix: {fix}")


def main():
    include = read(K0S_INCLUDE)
    atoms = {
        "k0s-k8s-version": scalar(include, "k0s-k8s-version", "include/k0s.yml"),
        "k0s-patch": scalar(include, "k0s-patch", "include/k0s.yml"),
    }
    upstream_tag = expand(
        scalar(include, "k0s-upstream-tag", "include/k0s.yml"),
        atoms,
        "include/k0s.yml k0s-upstream-tag",
    )
    version = expand(
        scalar(include, "k0s-version", "include/k0s.yml"),
        atoms,
        "include/k0s.yml k0s-version",
    )

    if not SAFE_VERSION_RE.match(version):
        fail(
            f"derived k0s-version {version!r} is not filename-safe.\n"
            "  It becomes a GitHub release asset name and is parsed back out by\n"
            "  the '@v' wildcard in files/os/sysupdate.d/70-k0s.transfer.",
            "restrict k0s-version to [A-Za-z0-9._~^+-] in include/k0s.yml.",
        )

    # The upstream download URL must be derived, not restated.
    bin_text = read(K0S_BIN)
    url_match = re.search(r"^\s*url:\s*(\S+)\s*$", bin_text, re.MULTILINE)
    if not url_match:
        fail(
            "elements/k0s/k0s-bin.bst declares no source 'url:'.",
            "restore the pinned upstream k0s release URL.",
        )
    url = url_match.group(1)
    if "%{k0s-upstream-tag}" not in url:
        fail(
            "elements/k0s/k0s-bin.bst hardcodes the upstream k0s release tag:\n"
            f"  url: {url}\n"
            "  A hardcoded tag drifts from include/k0s.yml, so the binary and\n"
            "  the version stamped into the sysext can disagree.",
            "use 'url: github:k0sproject/k0s/releases/download/"
            "%{k0s-upstream-tag}/k0s-%{k0s-upstream-tag}-amd64'.",
        )

    # The asset filename must be on the k0s axis, not the OS release axis.
    sysext_text = read(K0S_SYSEXT)
    fname_match = re.search(r'^\s*FNAME="([^"]+)"\s*$', sysext_text, re.MULTILINE)
    if not fname_match:
        fail(
            'elements/oci/k0s-sysext.bst declares no FNAME="..." asset name.',
            "restore the sysext asset filename assignment.",
        )
    fname_expr = fname_match.group(1)
    if "%{release-version}" in fname_expr:
        fail(
            "elements/oci/k0s-sysext.bst names the k0s sysext on the OS release\n"
            f"  axis: FNAME=\"{fname_expr}\"\n"
            "  70-k0s.transfer reads this filename as the version of the k0s it\n"
            "  delivers.",
            'use FNAME="k0s-%{k0s-version}.raw".',
        )
    if "%{k0s-version}" not in fname_expr:
        fail(
            "elements/oci/k0s-sysext.bst does not derive the sysext asset name\n"
            f"  from the pinned k0s version: FNAME=\"{fname_expr}\"",
            'use FNAME="k0s-%{k0s-version}.raw".',
        )

    # VERSION_ID must be generated, so sysext status matches the asset.
    if 'echo "VERSION_ID=%{k0s-version}"' not in sysext_text:
        fail(
            "elements/oci/k0s-sysext.bst does not generate VERSION_ID= from\n"
            "  %{k0s-version}, so `systemd-sysext status` can disagree with the\n"
            "  asset filename an operator sees on disk.",
            'append \'VERSION_ID=%{k0s-version}\' to the staged '
            "extension-release.k0s.",
        )

    ext_text = read(EXTENSION_RELEASE)
    stale = [
        line
        for line in ext_text.splitlines()
        if line.strip().startswith("VERSION_ID=")
    ]
    if stale:
        fail(
            "files/k0s/sysext/extension-release.k0s hardcodes a version:\n"
            f"  {stale[0]}\n"
            "  It is appended at build time from %{k0s-version}; a literal here\n"
            "  is a second, silently-winning source of truth.",
            "delete the VERSION_ID= line from "
            "files/k0s/sysext/extension-release.k0s.",
        )

    for path in (K0S_BIN, K0S_SYSEXT, EXTENSION_RELEASE):
        for line in read(path).splitlines():
            if line.lstrip().startswith("#"):
                continue
            found = LITERAL_VERSION_RE.search(line)
            if found:
                fail(
                    f"{path.relative_to(ROOT)} restates a literal k0s version:\n"
                    f"  {line.strip()}\n"
                    f"  Literal: {found.group(0)}",
                    "read the version from include/k0s.yml via "
                    "%{k0s-upstream-tag} or %{k0s-version}.",
                )

    # The produced asset name must satisfy the sysupdate transfer pattern.
    asset = fname_expr.replace("%{k0s-version}", version) + ".zst"
    transfer_text = read(TRANSFER)
    pattern_match = re.search(
        r"^\s*MatchPattern=(\S*@v\S*\.zst)\s*$", transfer_text, re.MULTILINE
    )
    if not pattern_match:
        fail(
            "files/os/sysupdate.d/70-k0s.transfer declares no [Source]\n"
            "  MatchPattern=...@v....zst.",
            "restore the sysupdate source MatchPattern.",
        )
    pattern = pattern_match.group(1)
    prefix, _, suffix = pattern.partition("@v")
    captured = None
    if (
        asset.startswith(prefix)
        and asset.endswith(suffix)
        and len(asset) >= len(prefix) + len(suffix)
    ):
        captured = asset[len(prefix) : len(asset) - len(suffix)]
    if captured != version:
        fail(
            "the version systemd-sysupdate would read from the k0s sysext asset\n"
            "  name is not the pinned k0s version:\n"
            f"  built asset    : {asset}\n"
            f"  MatchPattern   : {pattern}\n"
            f"  '@v' captures  : {captured!r}\n"
            f"  k0s-version    : {version!r}\n"
            "  Hosts compare the captured string against the version they have\n"
            "  installed, so a mismatch means k0s updates silently stop.",
            "align FNAME in elements/oci/k0s-sysext.bst with MatchPattern in "
            "files/os/sysupdate.d/70-k0s.transfer.",
        )

    print(
        f"OK: k0s {upstream_tag} pinned in include/k0s.yml; "
        f"asset {asset} matches {pattern} and VERSION_ID={version}."
    )


if __name__ == "__main__":
    main()
