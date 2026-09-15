#!/usr/bin/env python3
"""Generate the Flatcar-to-FSDK version parity matrix (issue #142).

Bluefin Server is composed from freedesktop-sdk 26.08 ``components/*`` while its
kernel and out-of-tree modules come from Flatcar stable 4593.2.5.  The
flatcar-base-migration design (phase 2, "version audit") needs one thing before
any substitution can be ordered: a matrix that says, for every component
Flatcar ships, what version Flatcar builds and what version FSDK 26.08 pins,
and therefore how far apart they are.

This script *generates* that matrix from sources rather than hand-writing it:

  * ``data/flatcar/<version>/version.txt`` — ``FLATCAR_VERSION``.
  * ``data/flatcar/<version>/flatcar_production_image_sbom.json`` — SPDX SBOM
    (``pkg:gentoo/<category/name>``), the source of every substituted
    component's Flatcar version (e.g. ``sys-fs/xfsprogs``).  The matrix omits a
    component whose Flatcar version cannot be found in the SBOM.
  * ``fsdk-versions.json`` — the FSDK 26.08 pin snapshot (component, version,
    element path, source).  Generated from the FSDK junction source; see the
    README.

The output is checked in at ``flatcar-to-fsdk-parity-matrix.md`` (and the same
rows as ``flatcar-to-fsdk-parity-matrix.csv``).  Re-run this script to refresh
the matrix after a Flatcar bump or an FSDK update.
"""

import csv
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
PARITY_DIR = SCRIPT_DIR
FLATCAR_DIR = ROOT / "data" / "flatcar"
FSDK_VERSIONS = PARITY_DIR / "fsdk-versions.json"
MD_OUT = PARITY_DIR / "flatcar-to-fsdk-parity-matrix.md"
CSV_OUT = PARITY_DIR / "flatcar-to-fsdk-parity-matrix.csv"

# The components the OS payload actually substitutes (design doc, "Overlay:
# what Flatcar displaces" + the version anchors).  Each entry is a
# (Gentoo atom in Flatcar's manifest, FSDK public component name) pair.
IN_SCOPE = [
    ("sys-apps/systemd", "systemd"),
    ("sys-libs/glibc", "glibc"),
    ("sys-apps/coreutils", "coreutils"),
    ("app-shells/bash", "bash"),
    ("net-misc/openssh", "openssh"),
    ("sys-apps/dbus", "dbus"),
    ("sys-apps/kmod", "kmod"),
    ("sys-apps/shadow", "shadow"),
    ("sys-fs/xfsprogs", "xfsprogs"),
    ("app-crypt/gnupg", "gnupg"),
    ("dev-libs/glib", "glib"),
    ("net-misc/curl", "curl"),
    ("dev-libs/openssl", "openssl"),
    ("sys-apps/util-linux", "util-linux"),
    ("sys-libs/libcap", "libcap"),
    ("dev-libs/libffi", "libffi"),
    ("app-arch/zstd", "zstd"),
    ("app-misc/ca-certificates", "ca-certificates"),
]

# Ordering guidance for the substitution work (design phase 6, "working down the
# parity matrix").  Load-bearing components boot the system and are substituted
# first; deferred items are optional payloads or prebuilt sysexts.
PRIORITY = {
    "systemd": "load-bearing",
    "glibc": "load-bearing",
    "coreutils": "important",
    "bash": "important",
    "openssh": "important",
    "dbus": "important",
    "kmod": "important",
    "shadow": "important",
    "gnupg": "important",
    "openssl": "important",
    "glib": "important",
    "curl": "important",
    "util-linux": "important",
    "libcap": "important",
    "libffi": "important",
    "zstd": "important",
    "xfsprogs": "deferred",
    "ca-certificates": "deferred",
}

# Gap overrides for rows that are not a plain same-scheme version comparison.
#   bootstrap      - FSDK provides it from the bootstrap, not components/*
#   imported       - Flatcar ships a prebuilt artifact, not a portage build
#   different-scheme - the two version strings are not comparable
#   n/a             - FSDK does not provide this component (kernel)
GAP_OVERRIDE = {
    "glibc": "bootstrap",
    "podman": "imported",
    "ca-certificates": "different-scheme",
}


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def parse_version(text):
    """Parse a dotted-numeric version prefix into a list of ints, or None."""
    if not text:
        return None
    s = re.sub(r"[-_](?:r|p|pre|rc|beta|alpha|post)\d*", ".", text, flags=re.I)
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)*)", s)
    if not m:
        return None
    return [int(x) for x in m.group(1).split(".")]


def version_cmp(fcar, fsdk):
    """Return -1/0/1 comparing Flatcar vs FSDK versions, or None if uncomparable."""
    if not fcar or not fsdk:
        return None
    for v in (fcar, fsdk):
        if re.search(r"-g[0-9a-f]{6,}|\.fc\d|\.el\d", v or ""):
            return None
    pa, pb = parse_version(fcar), parse_version(fsdk)
    if pa is None or pb is None:
        return None
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    if pa == pb:
        return 0
    return -1 if pa < pb else 1


def gap_for(component, fcar, fsdk):
    if component in GAP_OVERRIDE:
        return GAP_OVERRIDE[component]
    c = version_cmp(fcar, fsdk)
    if c is None:
        return "uncomparable"
    if c == 0:
        return "none"
    return "fsdk-newer" if c < 0 else "flatcar-newer"


def _sbom_versions(path):
    """SPDX SBOM -> ``pkg:gentoo/<category/name>`` -> versionInfo."""
    sbom = json.loads(read(path))
    out = {}
    for pkg in sbom.get("packages", []):
        pu = ""
        for ref in pkg.get("externalRefs", []) or []:
            loc = (ref.get("externalReference") or ref).get("referenceLocator", "")
            if loc.startswith("pkg:gentoo/"):
                pu = loc[len("pkg:gentoo/"):]
        key = pu.split("@")[0] if pu else pkg.get("name", "")
        if key:
            out[key] = pkg.get("versionInfo")
    return out


def load_flatcar_versions(fsdk_versions):
    version_txt = next(iter(FLATCAR_DIR.glob("*/version.txt")))
    flatcar_version = re.search(
        r"FLATCAR_VERSION=([0-9.]+)", read(version_txt)
    ).group(1)

    from_sbom = {}
    for p in sorted(FLATCAR_DIR.glob("*/flatcar_production_image_sbom.json")):
        from_sbom = _sbom_versions(p)
        break

    def flatcar_for(atom):
        if atom in from_sbom:
            return from_sbom[atom], "flatcar_production_image_sbom.json"
        return None, None

    rows = []
    for atom, component in IN_SCOPE:
        ver, src = flatcar_for(atom)
        fsdk = fsdk_versions.get(component)
        if ver is None or not fsdk:
            continue
        rows.append({
            "component": component,
            "flatcar_version": ver,
            "flatcar_source": src,
            "fsdk_version": fsdk["version"],
            "fsdk_element": fsdk["element_path"],
            "fsdk_source": fsdk["source"],
            "gap": gap_for(component, ver, fsdk["version"]),
            "priority": PRIORITY.get(component, "important"),
        })

    # Special rows that are not portage atoms in the Flatcar manifest.
    rows.append({
        "component": "kernel",
        "flatcar_version": f"{flatcar_version} (6.12.102-flatcar)",
        "flatcar_source": "version.txt + include/flatcar.yml",
        "fsdk_version": "n/a",
        "fsdk_element": "flatcar/flatcar-kernel.bst",
        "fsdk_source": "imported, not FSDK-built",
        "gap": "n/a",
        "priority": "load-bearing",
    })
    rows.append({
        "component": "podman",
        "flatcar_version": "prebuilt sysext (flatcar-podman.raw)",
        "flatcar_source": "flatcar_production_image (prebuilt sysext)",
        "fsdk_version": fsdk_versions.get("podman", {}).get("version", "?"),
        "fsdk_element": "components/podman.bst",
        "fsdk_source": "components/podman.bst",
        "gap": "imported",
        "priority": "deferred",
    })

    order = {"load-bearing": 0, "important": 1, "deferred": 2}
    rows.sort(key=lambda r: (order[r["priority"]], r["component"]))
    return flatcar_version, rows


MD_HEADER = """# Flatcar-to-FSDK parity matrix

**Flatcar {fcar} vs freedesktop-sdk 26.08 — version audit (design phase 2,
issue #142).** Generated by `arch/parity/generate-parity-matrix.py` from the
sources below; do not edit by hand — re-run the script.

Flatcar sources: `data/flatcar/{fcar}/` (`flatcar_production_image_sbom.json`,
`version.txt`). FSDK sources:
`fsdk-versions.json` (pinned to the `freedesktop-sdk-26.08` junction ref in
`elements/freedesktop-sdk.bst`).

| Component | Flatcar version | FSDK 26.08 version | Gap | Element path | Ordering |
|---|---|---|---|---|---|
"""

GAP_NOTES = """
## Gap

- `none` — FSDK already pins Flatcar's version; no substitution.
- `fsdk-newer` — FSDK pins a newer version; substitute by pinning the FSDK
  element to Flatcar's version.
- `flatcar-newer` — Flatcar pins a newer version than FSDK; upstream FSDK
  element or backport.
- `bootstrap` — FSDK provides it from the bootstrap, not `components/*`.
- `imported` — Flatcar ships a prebuilt artifact (sysext); FSDK builds it from
  source.
- `different-scheme` / `uncomparable` — the version strings use different
  schemes and cannot be ordered.
- `n/a` — FSDK does not provide this component (imported whole).

## Ordering guidance

- **load-bearing** — boot the system (systemd, glibc, kernel). Substitute first;
  every later phase depends on these.
- **important** — base userspace the installer and runtime depend on (coreutils,
  openssh, bash, dbus, kmod, shadow, gnupg, openssl, glib, curl, util-linux,
  libcap, libffi, zstd).
- **deferred** — optional payloads or prebuilt sysexts (xfsprogs,
  ca-certificates, podman).

## Source citations

Every row names its FSDK element path in the table above. FSDK versions are
read from the junction source; the full component snapshot lives in
`fsdk-versions.json`. The Flatcar source for each row is in
`flatcar-to-fsdk-parity-matrix.csv`.
"""


def render_markdown(fcar_version, rows):
    lines = [MD_HEADER.format(fcar=fcar_version).rstrip("\n")]
    for r in rows:
        lines.append(
            f"| {r['component']} | {r['flatcar_version']} "
            f"| {r['fsdk_version']} | {r['gap']} "
            f"| `{r['fsdk_element']}` | {r['priority']} |"
        )
    lines.append(GAP_NOTES)
    return "\n".join(lines) + "\n"


def render_csv(rows):
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[
        "component", "flatcar_version", "flatcar_source",
        "fsdk_version", "fsdk_element", "fsdk_source", "gap", "priority"])
    w.writeheader()
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


def main():
    if not FSDK_VERSIONS.is_file():
        sys.exit(f"ERROR: {FSDK_VERSIONS.relative_to(ROOT)} not found")
    fsdk_versions = json.loads(read(FSDK_VERSIONS))
    flatcar_version, rows = load_flatcar_versions(fsdk_versions)

    MD_OUT.write_text(render_markdown(fcar_version=flatcar_version, rows=rows), encoding="utf-8")
    CSV_OUT.write_text(render_csv(rows), encoding="utf-8")
    print(f"wrote {MD_OUT.name} and {CSV_OUT.name} ({len(rows)} rows, "
          f"Flatcar {flatcar_version})")


if __name__ == "__main__":
    main()
