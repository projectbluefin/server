#!/usr/bin/env python3
"""Generate the Flatcar-to-FSDK version parity matrix (issue #142).

Bluefin Server composes its OS payload from freedesktop-sdk 26.08 components
while its kernel and reference binaries derive from Flatcar Container Linux
(pinned at 4593.2.5 in include/flatcar.yml). Phase 2 of the Flatcar version
parity design (issue #142) requires an authoritative parity matrix: for each
in-scope component, record what version Flatcar ships, what version FSDK 26.08
pins, the version gap, and substitution priority.

This script generates that matrix into docs/skills/flatcar-parity-matrix.md
from pinned upstream artifacts:
  - version.txt (FLATCAR_VERSION and build ID)
  - flatcar_production_image_packages.txt (base system portage atoms and versions)
  - flatcar-podman_packages.txt (Flatcar podman sysext package atom and version)
  - elements/freedesktop-sdk.bst (junction ref to FSDK 26.08)

To ensure reproducibility without committing large vendored binaries, upstream
artifacts are verified against pinned SHA256 checksums and cached in
.cache/flatcar/<version>/ (which is gitignored).
"""

import argparse
import hashlib
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FLATCAR_INCLUDE = ROOT / "include" / "flatcar.yml"
FSDK_JUNCTION = ROOT / "elements" / "freedesktop-sdk.bst"
DEFAULT_OUTPUT = ROOT / "docs" / "skills" / "flatcar-parity-matrix.md"
DEFAULT_CACHE_DIR = ROOT / ".cache" / "flatcar"

FLATCAR_BASE_URL = "https://flatcar.cdn.cncf.io/stable"

# Pinned SHA256 checksums for upstream Flatcar 4593.2.5 artifacts.
PINNED_ARTIFACTS = {
    "4593.2.5": {
        "amd64-usr": {
            "version.txt": "6e86c457e9c3a622bbf1bd91874d16b121585fbec01813275c031ff52bbd227c",
            "flatcar_production_image_packages.txt": "58a437870d44c9bef66cc7b8186859de0071a9286a896535fff8e8e908aaedc2",
            "flatcar-podman_packages.txt": "befde0acac87cc8e6e24b4c1863e0ef03d689bbf6d2900b93bbc9f0a766ad7b1",
        }
    }
}

# The components in scope for the OS payload substitution audit.
# Derived from the design document ("Overlay: what Flatcar displaces" + version anchors).
IN_SCOPE_COMPONENTS = [
    {
        "component": "glibc",
        "atom": "sys-libs/glibc",
        "fsdk_version": "2.44-23",
        "fsdk_element": "bootstrap/glibc.bst",
        "fsdk_source": "bootstrap/glibc-source.yml",
        "priority": "load-bearing",
    },
    {
        "component": "kernel",
        "atom": None,
        "fsdk_version": "n/a",
        "fsdk_element": "flatcar/flatcar-kernel.bst",
        "fsdk_source": "imported, not FSDK-built",
        "priority": "load-bearing",
    },
    {
        "component": "systemd",
        "atom": "sys-apps/systemd",
        "fsdk_version": "261.2",
        "fsdk_element": "components/systemd.bst",
        "fsdk_source": "include/systemd.yml",
        "priority": "load-bearing",
    },
    {
        "component": "bash",
        "atom": "app-shells/bash",
        "fsdk_version": "5.3-16",
        "fsdk_element": "bootstrap/bash.bst",
        "fsdk_source": "bootstrap/bash-source.yml",
        "priority": "important",
    },
    {
        "component": "coreutils",
        "atom": "sys-apps/coreutils",
        "fsdk_version": "9.11",
        "fsdk_element": "bootstrap/coreutils.bst",
        "fsdk_source": "bootstrap/coreutils-source.yml",
        "priority": "important",
    },
    {
        "component": "curl",
        "atom": "net-misc/curl",
        "fsdk_version": "8.21.0",
        "fsdk_element": "components/curl.bst",
        "fsdk_source": "components/curl.bst",
        "priority": "important",
    },
    {
        "component": "dbus",
        "atom": "sys-apps/dbus",
        "fsdk_version": "1.16.2",
        "fsdk_element": "components/dbus.bst",
        "fsdk_source": "components/dbus.bst",
        "priority": "important",
    },
    {
        "component": "glib",
        "atom": "dev-libs/glib",
        "fsdk_version": "2.88.3",
        "fsdk_element": "components/glib.bst",
        "fsdk_source": "components/glib.bst",
        "priority": "important",
    },
    {
        "component": "gnupg",
        "atom": "app-crypt/gnupg",
        "fsdk_version": "2.4.9",
        "fsdk_element": "components/gnupg.bst",
        "fsdk_source": "components/gnupg.bst",
        "priority": "important",
    },
    {
        "component": "kmod",
        "atom": "sys-apps/kmod",
        "fsdk_version": "34.2",
        "fsdk_element": "components/kmod.bst",
        "fsdk_source": "components/kmod.bst",
        "priority": "important",
    },
    {
        "component": "libcap",
        "atom": "sys-libs/libcap",
        "fsdk_version": "2.78",
        "fsdk_element": "components/libcap.bst",
        "fsdk_source": "components/libcap.bst",
        "priority": "important",
    },
    {
        "component": "libffi",
        "atom": "dev-libs/libffi",
        "fsdk_version": "3.8.0",
        "fsdk_element": "components/libffi.bst",
        "fsdk_source": "components/libffi.bst",
        "priority": "important",
    },
    {
        "component": "openssh",
        "atom": "net-misc/openssh",
        "fsdk_version": "10.5.P1",
        "fsdk_element": "components/openssh.bst",
        "fsdk_source": "components/openssh.bst",
        "priority": "important",
    },
    {
        "component": "openssl",
        "atom": "dev-libs/openssl",
        "fsdk_version": "3.5.8",
        "fsdk_element": "components/openssl.bst",
        "fsdk_source": "components/openssl.bst",
        "priority": "important",
    },
    {
        "component": "shadow",
        "atom": "sys-apps/shadow",
        "fsdk_version": "4.20.2",
        "fsdk_element": "components/shadow.bst",
        "fsdk_source": "components/shadow.bst",
        "priority": "important",
    },
    {
        "component": "util-linux",
        "atom": "sys-apps/util-linux",
        "fsdk_version": "2.42.2",
        "fsdk_element": "components/util-linux.bst",
        "fsdk_source": "components/util-linux.bst",
        "priority": "important",
    },
    {
        "component": "zstd",
        "atom": "app-arch/zstd",
        "fsdk_version": "1.5.7",
        "fsdk_element": "components/zstd.bst",
        "fsdk_source": "components/zstd.bst",
        "priority": "important",
    },
    {
        "component": "ca-certificates",
        "atom": "app-misc/ca-certificates",
        "fsdk_version": "2010.63-3.fc14-175",
        "fsdk_element": "components/ca-certificates.bst",
        "fsdk_source": "components/ca-certificates.bst",
        "priority": "deferred",
        "gap_override": "different-scheme",
    },
    {
        "component": "podman",
        "atom": "app-containers/podman",
        "fsdk_version": "6.1.0",
        "fsdk_element": "components/podman.bst",
        "fsdk_source": "components/podman.bst",
        "priority": "deferred",
        "sysext": "flatcar-podman.raw",
    },
    {
        "component": "xfsprogs",
        "atom": "sys-fs/xfsprogs",
        "fsdk_version": "7.1.1",
        "fsdk_element": "components/xfsprogs.bst",
        "fsdk_source": "components/xfsprogs.bst",
        "priority": "deferred",
    },
]

PRIORITY_ORDER = {"load-bearing": 0, "important": 1, "deferred": 2}


def read_text(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path}")
    return path.read_text(encoding="utf-8")


def get_flatcar_pinned_version():
    """Read flatcar-version from include/flatcar.yml."""
    content = read_text(FLATCAR_INCLUDE)
    match = re.search(r"^\s*flatcar-version:\s*[\"']?([0-9.]+)[\"']?\s*$", content, re.MULTILINE)
    if not match:
        sys.exit("ERROR: include/flatcar.yml does not declare 'flatcar-version:'")
    return match.group(1)


def get_flatcar_pinned_kver():
    """Read flatcar-kver from include/flatcar.yml."""
    content = read_text(FLATCAR_INCLUDE)
    match = re.search(r"^\s*flatcar-kver:\s*[\"']?([^\s\"']+)[\"']?\s*$", content, re.MULTILINE)
    if not match:
        sys.exit("ERROR: include/flatcar.yml does not declare 'flatcar-kver:'")
    return match.group(1)


def check_fsdk_junction_ref():
    """Verify that elements/freedesktop-sdk.bst pins freedesktop-sdk-26.08.*."""
    content = read_text(FSDK_JUNCTION)
    match = re.search(r"freedesktop-sdk-(26\.08\.[0-9]+)", content)
    if not match:
        sys.exit("ERROR: elements/freedesktop-sdk.bst does not pin freedesktop-sdk-26.08.*")
    return match.group(1)


def verify_sha256(data, expected_sha):
    actual = hashlib.sha256(data).hexdigest()
    return actual == expected_sha, actual


def fetch_or_load_artifact(filename, expected_sha, cache_dir, version, board="amd64-usr"):
    """Load artifact from cache or fetch from Flatcar CDN if missing/checksum mismatch."""
    path = cache_dir / filename
    if path.is_file():
        valid, _ = verify_sha256(path.read_bytes(), expected_sha)
        if valid:
            return path.read_text(encoding="utf-8")

    # Download from CDN
    url = f"{FLATCAR_BASE_URL}/{board}/{version}/{filename}"
    req = urllib.request.Request(url, headers={"User-Agent": "curl/7.88.1 (bluefin-server parity generator)"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
    except Exception as exc:
        sys.exit(f"ERROR: failed to fetch {url}: {exc}")

    valid, actual_sha = verify_sha256(data, expected_sha)
    if not valid:
        sys.exit(
            f"ERROR: checksum mismatch for {filename} from {url}:\n"
            f"  expected: {expected_sha}\n"
            f"  got     : {actual_sha}"
        )

    cache_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data.decode("utf-8")


def parse_packages_manifest(content):
    """Parse flatcar_production_image_packages.txt (or sysext packages file)."""
    packages = {}
    pattern = re.compile(r"^([a-z0-9+._-]+/[a-z0-9+._-]+?)-([0-9]+.*)$")
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        pkg_part = line.split("::")[0].strip()
        m = pattern.match(pkg_part)
        if m:
            atom = m.group(1)
            version = m.group(2)
            packages[atom] = version
    return packages


def parse_spdx_sbom(content):
    """Parse SPDX SBOM JSON if present, returning {atom: version}."""
    sbom = json.loads(content)
    packages = {}
    for pkg in sbom.get("packages", []):
        locator = ""
        for ref in pkg.get("externalRefs", []) or []:
            ref_loc = (ref.get("externalReference") or ref).get("referenceLocator", "")
            if ref_loc.startswith("pkg:gentoo/"):
                locator = ref_loc[len("pkg:gentoo/"):]
                break
        atom = locator.split("@")[0] if locator else pkg.get("name", "")
        version = pkg.get("versionInfo")
        if atom and version:
            packages[atom] = version
    return packages


def parse_version_prefix(text):
    """Extract numeric components for version comparison."""
    if not text:
        return None
    s = re.sub(r"[-_](?:r|p|pre|rc|beta|alpha|post)\d*", ".", text, flags=re.I)
    m = re.match(r"\s*([0-9]+(?:\.[0-9]+)*)", s)
    if not m:
        return None
    return [int(x) for x in m.group(1).split(".")]


def compare_versions(v_fcar, v_fsdk):
    """Compare Flatcar version against FSDK version.

    Returns -1 if v_fcar < v_fsdk (fsdk is newer),
             0 if equal (none),
             1 if v_fcar > v_fsdk (flatcar is newer),
          None if uncomparable.
    """
    if not v_fcar or not v_fsdk:
        return None
    p_fcar = parse_version_prefix(v_fcar)
    p_fsdk = parse_version_prefix(v_fsdk)
    if p_fcar is None or p_fsdk is None:
        return None
    max_len = max(len(p_fcar), len(p_fsdk))
    p_fcar += [0] * (max_len - len(p_fcar))
    p_fsdk += [0] * (max_len - len(p_fsdk))
    if p_fcar == p_fsdk:
        return 0
    return -1 if p_fcar < p_fsdk else 1


def compute_gap(component_spec, flatcar_ver, fsdk_ver):
    """Calculate the version gap between Flatcar and FSDK."""
    if "gap_override" in component_spec:
        return component_spec["gap_override"]
    if fsdk_ver == "n/a" or flatcar_ver == "n/a":
        return "n/a"
    cmp_res = compare_versions(flatcar_ver, fsdk_ver)
    if cmp_res is None:
        return "different-scheme"
    if cmp_res == 0:
        return "none"
    return "fsdk-newer" if cmp_res < 0 else "flatcar-newer"


def collect_flatcar_versions(flatcar_dir=None, flatcar_version="4593.2.5", board="amd64-usr"):
    """Load package versions from flatcar_dir or download via CDN with SHA256 pin verification."""
    packages = {}
    sources = {}

    if flatcar_dir and Path(flatcar_dir).is_dir():
        d = Path(flatcar_dir)
        # Check for version.txt
        v_files = sorted(d.glob("**/version.txt"))
        if not v_files:
            sys.exit(f"ERROR: no version.txt found in {flatcar_dir}")
        v_txt = read_text(v_files[0])
        m = re.search(r"FLATCAR_VERSION=([0-9.]+)", v_txt)
        if m:
            flatcar_version = m.group(1)

        # Check for SBOM
        sbom_files = sorted(d.glob("**/flatcar_production_image_sbom.json"))
        if sbom_files:
            sbom_pkgs = parse_spdx_sbom(read_text(sbom_files[0]))
            packages.update(sbom_pkgs)
            for atom in sbom_pkgs:
                sources[atom] = "flatcar_production_image_sbom.json"

        # Check for packages manifest
        pkg_files = sorted(d.glob("**/flatcar_production_image_packages.txt"))
        if pkg_files:
            manifest_pkgs = parse_packages_manifest(read_text(pkg_files[0]))
            for atom, ver in manifest_pkgs.items():
                if atom not in packages:
                    packages[atom] = ver
                    sources[atom] = "flatcar_production_image_packages.txt"

        # Check for podman packages
        podman_pkg_files = sorted(d.glob("**/flatcar-podman_packages.txt"))
        if podman_pkg_files:
            podman_pkgs = parse_packages_manifest(read_text(podman_pkg_files[0]))
            for atom, ver in podman_pkgs.items():
                packages[atom] = ver
                sources[atom] = "flatcar-podman_packages.txt"

        return flatcar_version, packages, sources

    # Cache / CDN fetch path
    cache_dir = DEFAULT_CACHE_DIR / flatcar_version
    pins = PINNED_ARTIFACTS.get(flatcar_version, {}).get(board, {})
    if not pins:
        sys.exit(f"ERROR: no pinned artifacts for Flatcar {flatcar_version} ({board})")

    # Fetch version.txt
    v_txt = fetch_or_load_artifact("version.txt", pins["version.txt"], cache_dir, flatcar_version, board)
    m = re.search(r"FLATCAR_VERSION=([0-9.]+)", v_txt)
    if m:
        flatcar_version = m.group(1)

    # Fetch base packages manifest
    pkg_txt = fetch_or_load_artifact(
        "flatcar_production_image_packages.txt",
        pins["flatcar_production_image_packages.txt"],
        cache_dir,
        flatcar_version,
        board,
    )
    manifest_pkgs = parse_packages_manifest(pkg_txt)
    for atom, ver in manifest_pkgs.items():
        packages[atom] = ver
        sources[atom] = "flatcar_production_image_packages.txt"

    # Fetch podman packages manifest
    podman_txt = fetch_or_load_artifact(
        "flatcar-podman_packages.txt",
        pins["flatcar-podman_packages.txt"],
        cache_dir,
        flatcar_version,
        board,
    )
    podman_pkgs = parse_packages_manifest(podman_txt)
    for atom, ver in podman_pkgs.items():
        packages[atom] = ver
        sources[atom] = "flatcar-podman_packages.txt"

    return flatcar_version, packages, sources


def clean_ticket_version(comp, v):
    """Normalize version string for downstream ticket description."""
    if comp == "systemd":
        return v.split(".")[0]
    return re.sub(r"[-_](?:r|p)\d+.*$", "", v)


def build_matrix_rows(flatcar_version, packages, sources, strict=True):
    """Build the matrix rows by resolving each in-scope component."""
    kver = get_flatcar_pinned_kver()
    rows = []
    missing_atoms = []
    for spec in IN_SCOPE_COMPONENTS:
        comp = spec["component"]
        atom = spec["atom"]
        fsdk_ver = spec["fsdk_version"]
        fsdk_elem = spec["fsdk_element"]
        priority = spec["priority"]

        if comp == "kernel":
            flatcar_ver = f"{flatcar_version} ({kver})"
            flatcar_src = "version.txt + include/flatcar.yml"
        elif atom and atom in packages:
            flatcar_ver = packages[atom]
            flatcar_src = sources.get(atom, "flatcar_production_image_packages.txt")
        else:
            if strict:
                missing_atoms.append(f"{comp} ({atom})")
            continue

        gap = compute_gap(spec, flatcar_ver, fsdk_ver)

        rows.append({
            "component": comp,
            "flatcar_version": flatcar_ver,
            "flatcar_source": flatcar_src,
            "fsdk_version": fsdk_ver,
            "fsdk_element": fsdk_elem,
            "fsdk_source": spec["fsdk_source"],
            "gap": gap,
            "priority": priority,
        })

    if missing_atoms:
        sys.exit(f"ERROR: in-scope components missing from Flatcar manifests: {', '.join(missing_atoms)}")

    rows.sort(key=lambda r: (PRIORITY_ORDER[r["priority"]], r["component"]))
    return rows


def render_markdown(flatcar_version, fsdk_version, rows):
    """Render docs/skills/flatcar-parity-matrix.md with valid skill frontmatter."""
    out = [
        "---",
        "name: flatcar-parity-matrix",
        "description: |",
        "  Flatcar-to-FSDK version parity matrix for Bluefin Server (issue #142). Tracks component",
        f"  versions, gaps, element paths, and substitution order against Flatcar {flatcar_version}.",
        "metadata:",
        "  type: reference",
        "  status: stable",
        '  last_updated: "2026-09-18"',
        "---",
        "# Flatcar-to-FSDK Parity Matrix",
        "",
        f"**Flatcar {flatcar_version} vs freedesktop-sdk 26.08 — version audit (design phase 2, issue #142).** "
        "Generated by `scripts/generate-parity-matrix.py` from pinned upstream release artifacts; "
        "do not edit by hand — re-run the generator.",
        "",
        "| Component | Flatcar version | FSDK 26.08 version | Gap | Element path | Ordering |",
        "|---|---|---|---|---|---|",
    ]

    for r in rows:
        out.append(
            f"| {r['component']} | {r['flatcar_version']} | {r['fsdk_version']} | "
            f"{r['gap']} | `{r['fsdk_element']}` | {r['priority']} |"
        )

    out.extend([
        "",
        "## Gap Definitions",
        "",
        "- `none` — FSDK already pins Flatcar's upstream version; no substitution required.",
        "- `fsdk-newer` — FSDK pins a newer upstream release than Flatcar; substitute by pinning or backporting the Flatcar version in FSDK elements.",
        "- `flatcar-newer` — Flatcar pins a newer upstream release than FSDK.",
        "- `different-scheme` — Component version strings follow different packaging schemes and cannot be ordered numerically (e.g. Mozilla NSS certdata vs Fedora RPM).",
        "- `n/a` — FSDK does not provide this component; imported whole as a reference.",
        "",
        "## Ordering Guidance",
        "",
        "- **load-bearing** — Boot-critical components (glibc, kernel, systemd). Must be substituted first because all subsequent layers depend on them.",
        "- **important** — Base userspace runtime and installer dependencies (bash, coreutils, curl, dbus, glib, gnupg, kmod, libcap, libffi, openssh, openssl, shadow, util-linux, zstd).",
        "- **deferred** — Optional payloads, sysext extensions, or filesystem utilities (ca-certificates, podman, xfsprogs).",
        "",
        "## Source Citations",
        "",
        f"- Flatcar release {flatcar_version} artifacts fetched from `https://flatcar.cdn.cncf.io/stable/amd64-usr/{flatcar_version}/` with SHA256 checksums pinned in `scripts/generate-parity-matrix.py`:",
        f"  - `version.txt` (`{PINNED_ARTIFACTS.get(flatcar_version, {}).get('amd64-usr', {}).get('version.txt', '6e86c457')[:8]}...`): release identifier and build ID.",
        f"  - `flatcar_production_image_packages.txt` (`{PINNED_ARTIFACTS.get(flatcar_version, {}).get('amd64-usr', {}).get('flatcar_production_image_packages.txt', '58a43787')[:8]}...`): installed Portage atoms and versions.",
        f"  - `flatcar-podman_packages.txt` (`{PINNED_ARTIFACTS.get(flatcar_version, {}).get('amd64-usr', {}).get('flatcar-podman_packages.txt', 'befde0ac')[:8]}...`): container runtime sysext packages.",
        f"- FSDK 26.08 source elements: pinned junction ref `freedesktop-sdk-{fsdk_version}` in `elements/freedesktop-sdk.bst`.",
        "",
        "## Downstream Substitution Tickets",
        "",
        "The following substitution tickets are derived directly from the matrix ordering:",
        "",
        "1. **Load-bearing (phase 6a)**",
    ])

    rows_by_comp = {r["component"]: r for r in rows}
    kernel_entry = rows_by_comp.get("kernel", {})
    kernel_kver = kernel_entry.get("flatcar_version", "").split()[-1].strip("()") if kernel_entry else ""
    glibc_ver = clean_ticket_version("glibc", rows_by_comp.get("glibc", {}).get("flatcar_version", ""))
    systemd_ver = clean_ticket_version("systemd", rows_by_comp.get("systemd", {}).get("flatcar_version", ""))

    out.append(f"   - `subst(kernel)`: reference import `flatcar/flatcar-kernel.bst` ({kernel_kver})")
    out.append(f"   - `subst(glibc)`: pin glibc {glibc_ver} in `bootstrap/glibc.bst`")
    out.append(f"   - `subst(systemd)`: pin systemd {systemd_ver} in `components/systemd.bst`")

    out.append("2. **Important base userspace (phase 6b)**")
    for comp in ["coreutils", "curl", "glib", "gnupg", "libcap", "libffi", "openssh", "openssl", "shadow", "util-linux"]:
        if comp in rows_by_comp:
            r = rows_by_comp[comp]
            v = clean_ticket_version(comp, r["flatcar_version"])
            out.append(f"   - `subst({comp})`: pin {comp} {v} in `{r['fsdk_element']}`")

    version_matches = []
    for comp in ["bash", "dbus", "kmod", "zstd"]:
        if comp in rows_by_comp:
            v = clean_ticket_version(comp, rows_by_comp[comp]["flatcar_version"])
            version_matches.append(f"`{comp}` ({v})")
    if version_matches:
        out.append(f"   - Version matches (verification only): {', '.join(version_matches)}")

    out.append("3. **Deferred (phase 6c)**")
    ca_ver = rows_by_comp.get("ca-certificates", {}).get("flatcar_version", "")
    podman_ver = clean_ticket_version("podman", rows_by_comp.get("podman", {}).get("flatcar_version", ""))
    xfs_ver = clean_ticket_version("xfsprogs", rows_by_comp.get("xfsprogs", {}).get("flatcar_version", ""))
    xfs_elem = rows_by_comp.get("xfsprogs", {}).get("fsdk_element", "components/xfsprogs.bst")
    out.append(f"   - `subst(ca-certificates)`: evaluate NSS certdata {ca_ver} vs Fedora packaging")
    out.append(f"   - `subst(podman)`: delivery via sysext matching Flatcar podman {podman_ver}")
    out.append(f"   - `subst(xfsprogs)`: pin xfsprogs {xfs_ver} in `{xfs_elem}`")

    return "\n".join(out) + "\n"


def print_substitution_tickets(rows):
    """Print issue titles and bodies for downstream substitution tickets."""
    print("=== Downstream Substitution Tickets ===")
    for r in rows:
        title = f"subst({r['component']}): align {r['component']} to Flatcar {r['flatcar_version']} ({r['fsdk_element']})"
        body = (
            f"Parity matrix row for {r['component']}:\n\n"
            f"- **Flatcar version**: {r['flatcar_version']} (source: {r['flatcar_source']})\n"
            f"- **FSDK 26.08 version**: {r['fsdk_version']} ({r['fsdk_element']})\n"
            f"- **Gap**: {r['gap']}\n"
            f"- **Ordering priority**: {r['priority']}\n"
        )
        print(f"Title: {title}")
        print(f"Priority: {r['priority']}")
        print(body)
        print("-" * 40)


def main():
    parser = argparse.ArgumentParser(description="Generate the Flatcar-to-FSDK version parity matrix.")
    parser.add_argument("--flatcar-dir", help="Path to local directory with Flatcar release artifacts.")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, type=Path, help="Output markdown path.")
    parser.add_argument("--check", action="store_true", help="Check that output file matches generated matrix.")
    parser.add_argument("--print-tickets", action="store_true", help="Print downstream substitution ticket specifications.")
    args = parser.parse_args()

    pinned_flatcar_ver = get_flatcar_pinned_version()
    fsdk_ver = check_fsdk_junction_ref()

    flatcar_version, packages, sources = collect_flatcar_versions(
        flatcar_dir=args.flatcar_dir,
        flatcar_version=pinned_flatcar_ver,
    )

    rows = build_matrix_rows(flatcar_version, packages, sources)
    rendered = render_markdown(flatcar_version, fsdk_ver, rows)

    if args.print_tickets:
        print_substitution_tickets(rows)
        return

    if args.check:
        if not args.output.is_file():
            sys.exit(f"ERROR: {args.output} does not exist. Re-run generator without --check.")
        existing = args.output.read_text(encoding="utf-8")
        if existing != rendered:
            sys.exit(f"ERROR: {args.output} is out of date. Re-run generator without --check to update.")
        print(f"OK: {args.output} is up to date.")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output} ({len(rows)} rows, Flatcar {flatcar_version} vs FSDK {fsdk_ver})")


if __name__ == "__main__":
    main()
