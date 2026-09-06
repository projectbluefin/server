#!/usr/bin/env python3
"""Enforce the k3s version invariant for Bluefin Server.

k3s is an independently-pinned third-party payload, not an OS asset, so it is
versioned on its own axis. ``include/k3s.yml`` is the single source of truth:

    variables:
      k3s-k8s-version: "1.36.2"
      k3s-patch: "1"
      k3s-upstream-tag: "v%{k3s-k8s-version}%2Bk3s%{k3s-patch}"
      k3s-version: "%{k3s-k8s-version}-k3s%{k3s-patch}"

Three consumers restate that version in three different spellings, and all
three must move together or the sysext silently stops updating:

  * ``elements/k3s/k3s-bin.bst``          — the upstream download URL.
  * ``elements/oci/k3s-sysext.bst``       — the release asset filename, which
    ``files/os/sysupdate.d/70-k3s.transfer`` reads as the version oracle
    through its ``@v`` wildcard.
  * ``files/k3s/sysext/extension-release.k3s`` — the ``VERSION_ID=`` reported
    by ``systemd-sysext status``.

Historically the filename was derived from ``%{release-version}`` (the OS
point release) while the payload and ``VERSION_ID`` were on the k3s axis. A
k3s security bump then left the filename unchanged, so sysupdate declined the
update; and every OS point release renamed a byte-identical sysext, forcing a
fleet-wide no-op re-download.

This script fails closed if any consumer reintroduces a literal k3s version or
drops back onto the OS release axis, and cross-checks that the derived asset
filename still matches the sysupdate transfer's MatchPattern.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K3S_INCLUDE = ROOT / "include" / "k3s.yml"
K3S_BIN = ROOT / "elements" / "k3s" / "k3s-bin.bst"
K3S_SYSEXT = ROOT / "elements" / "oci" / "k3s-sysext.bst"
EXTENSION_RELEASE = ROOT / "files" / "k3s" / "sysext" / "extension-release.k3s"
TRANSFER = ROOT / "files" / "os" / "sysupdate.d" / "70-k3s.transfer"

# systemd-sysupdate validates the string captured by `@v` with
# version_is_valid(VERSION_ALLOW_UNDERSCORE|VERSION_ALLOW_PLUS). GitHub also
# rewrites characters outside this set in release asset names, so the derived
# asset version must stay within it.
SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9._~^+-]+$")

# A literal upstream k3s version, in any of its spellings: v1.36.2+k3s1,
# v1.36.2%2Bk3s1, 1.36.2-k3s1.
LITERAL_VERSION_RE = re.compile(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:\+|%2B|-)k3s[0-9]+")


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
    include = read(K3S_INCLUDE)
    atoms = {
        "k3s-k8s-version": scalar(include, "k3s-k8s-version", "include/k3s.yml"),
        "k3s-patch": scalar(include, "k3s-patch", "include/k3s.yml"),
    }
    upstream_tag = expand(
        scalar(include, "k3s-upstream-tag", "include/k3s.yml"),
        atoms,
        "include/k3s.yml k3s-upstream-tag",
    )
    version = expand(
        scalar(include, "k3s-version", "include/k3s.yml"),
        atoms,
        "include/k3s.yml k3s-version",
    )

    if not SAFE_VERSION_RE.match(version):
        fail(
            f"derived k3s-version {version!r} is not filename-safe.\n"
            "  It becomes a GitHub release asset name and is parsed back out by\n"
            "  the '@v' wildcard in files/os/sysupdate.d/70-k3s.transfer.",
            "restrict k3s-version to [A-Za-z0-9._~^+-] in include/k3s.yml.",
        )

    # The upstream download URL must be derived, not restated.
    bin_text = read(K3S_BIN)
    url_match = re.search(r"^\s*url:\s*(\S+)\s*$", bin_text, re.MULTILINE)
    if not url_match:
        fail(
            "elements/k3s/k3s-bin.bst declares no source 'url:'.",
            "restore the pinned upstream k3s release URL.",
        )
    url = url_match.group(1)
    if "%{k3s-upstream-tag}" not in url:
        fail(
            "elements/k3s/k3s-bin.bst hardcodes the upstream k3s release tag:\n"
            f"  url: {url}\n"
            "  A hardcoded tag drifts from include/k3s.yml, so the binary and\n"
            "  the version stamped into the sysext can disagree.",
            "use 'url: github:k3s-io/k3s/releases/download/"
            "%{k3s-upstream-tag}/k3s'.",
        )

    # The asset filename must be on the k3s axis, not the OS release axis.
    sysext_text = read(K3S_SYSEXT)
    fname_match = re.search(r'^\s*FNAME="([^"]+)"\s*$', sysext_text, re.MULTILINE)
    if not fname_match:
        fail(
            'elements/oci/k3s-sysext.bst declares no FNAME="..." asset name.',
            "restore the sysext asset filename assignment.",
        )
    fname_expr = fname_match.group(1)
    if "%{release-version}" in fname_expr:
        fail(
            "elements/oci/k3s-sysext.bst names the k3s sysext on the OS release\n"
            f"  axis: FNAME=\"{fname_expr}\"\n"
            "  70-k3s.transfer reads this filename as the version of the k3s it\n"
            "  delivers. On the OS axis a k3s bump leaves the name unchanged (no\n"
            "  update ships) and an OS bump renames an identical sysext (every\n"
            "  host re-downloads it).",
            'use FNAME="k3s-%{k3s-version}.raw".',
        )
    if "%{k3s-version}" not in fname_expr:
        fail(
            "elements/oci/k3s-sysext.bst does not derive the sysext asset name\n"
            f"  from the pinned k3s version: FNAME=\"{fname_expr}\"",
            'use FNAME="k3s-%{k3s-version}.raw".',
        )

    # VERSION_ID must be generated, so sysext status matches the asset.
    if 'echo "VERSION_ID=%{k3s-version}"' not in sysext_text:
        fail(
            "elements/oci/k3s-sysext.bst does not generate VERSION_ID= from\n"
            "  %{k3s-version}, so `systemd-sysext status` can disagree with the\n"
            "  asset filename an operator sees on disk.",
            'append \'VERSION_ID=%{k3s-version}\' to the staged '
            "extension-release.k3s.",
        )

    ext_text = read(EXTENSION_RELEASE)
    stale = [
        line
        for line in ext_text.splitlines()
        if line.strip().startswith("VERSION_ID=")
    ]
    if stale:
        fail(
            "files/k3s/sysext/extension-release.k3s hardcodes a version:\n"
            f"  {stale[0]}\n"
            "  It is appended at build time from %{k3s-version}; a literal here\n"
            "  is a second, silently-winning source of truth.",
            "delete the VERSION_ID= line from "
            "files/k3s/sysext/extension-release.k3s.",
        )

    for path in (K3S_BIN, K3S_SYSEXT, EXTENSION_RELEASE):
        for line in read(path).splitlines():
            if line.lstrip().startswith("#"):
                continue
            found = LITERAL_VERSION_RE.search(line)
            if found:
                fail(
                    f"{path.relative_to(ROOT)} restates a literal k3s version:\n"
                    f"  {line.strip()}\n"
                    f"  Literal: {found.group(0)}",
                    "read the version from include/k3s.yml via "
                    "%{k3s-upstream-tag} or %{k3s-version}.",
                )

    # The produced asset name must satisfy the sysupdate transfer pattern.
    asset = fname_expr.replace("%{k3s-version}", version) + ".zst"
    transfer_text = read(TRANSFER)
    pattern_match = re.search(
        r"^\s*MatchPattern=(\S*@v\S*\.zst)\s*$", transfer_text, re.MULTILINE
    )
    if not pattern_match:
        fail(
            "files/os/sysupdate.d/70-k3s.transfer declares no [Source]\n"
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
            "the version systemd-sysupdate would read from the k3s sysext asset\n"
            "  name is not the pinned k3s version:\n"
            f"  built asset    : {asset}\n"
            f"  MatchPattern   : {pattern}\n"
            f"  '@v' captures  : {captured!r}\n"
            f"  k3s-version    : {version!r}\n"
            "  Hosts compare the captured string against the version they have\n"
            "  installed, so a mismatch means k3s updates silently stop.",
            "align FNAME in elements/oci/k3s-sysext.bst with MatchPattern in "
            "files/os/sysupdate.d/70-k3s.transfer.",
        )

    print(
        f"OK: k3s {upstream_tag} pinned in include/k3s.yml; "
        f"asset {asset} matches {pattern} and VERSION_ID={version}."
    )


if __name__ == "__main__":
    main()
