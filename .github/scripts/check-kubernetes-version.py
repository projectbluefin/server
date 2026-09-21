#!/usr/bin/env python3
"""Enforce the Kubernetes version invariant for Bluefin Server.

Kubernetes is an independently-pinned third-party payload, not an OS asset, so
it is versioned on its own axis. ``include/kubernetes.yml`` is the single
source of truth:

    variables:
      k8s-version: "1.36.4"
      cni-version: "1.9.1"
      k8s-upstream-tag: "v%{k8s-version}"
      cni-upstream-tag: "v%{cni-version}"

Four consumers restate that version in four different spellings, and all four
must move together or the sysext silently stops updating:

  * ``elements/kubernetes/kubernetes-bin.bst`` — the dl.k8s.io download URLs
    for kubectl, kubeadm and kubelet.
  * ``elements/kubernetes/cni-plugins.bst``    — the CNI plugins release URL.
  * ``elements/oci/kubernetes-sysext.bst``     — the release asset filename,
    which ``files/os/sysupdate.kubernetes.d/70-kubernetes.transfer`` reads as
    the version oracle through its ``@v`` wildcard, plus the two
    ``/usr/local/share/kubernetes-*version`` stamps.
  * ``files/kubernetes/sysext/extension-release.kubernetes`` — the
    ``VERSION_ID=`` reported by ``systemd-sysext status``.

This script fails closed if any consumer reintroduces a literal Kubernetes or
CNI version or drops back onto the OS release axis, and cross-checks that the
derived asset filename still matches the sysupdate transfer's MatchPattern.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
K8S_INCLUDE = ROOT / "include" / "kubernetes.yml"
K8S_BIN = ROOT / "elements" / "kubernetes" / "kubernetes-bin.bst"
CNI_BIN = ROOT / "elements" / "kubernetes" / "cni-plugins.bst"
K8S_SYSEXT = ROOT / "elements" / "oci" / "kubernetes-sysext.bst"
EXTENSION_RELEASE = (
    ROOT / "files" / "kubernetes" / "sysext" / "extension-release.kubernetes"
)
TRANSFER = (
    ROOT / "files" / "os" / "sysupdate.kubernetes.d" / "70-kubernetes.transfer"
)

SAFE_VERSION_RE = re.compile(r"^[A-Za-z0-9._~^+-]+$")
LITERAL_VERSION_RE = re.compile(r"(?<![0-9A-Za-z.])v?[0-9]+\.[0-9]+\.[0-9]+(?![0-9])")

# The three node binaries kubeadm and the kubelet unit expect on PATH. Each is
# fetched from its own pinned URL, so each URL has to be derived independently.
NODE_BINARIES = ("kubectl", "kubeadm", "kubelet")


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


def source_urls(text):
    """Every ``url:`` declared by the sources of a BuildStream element."""
    return re.findall(r"^\s*url:\s*(\S+)\s*$", text, re.MULTILINE)


def main():
    include = read(K8S_INCLUDE)
    atoms = {
        "k8s-version": scalar(include, "k8s-version", "include/kubernetes.yml"),
        "cni-version": scalar(include, "cni-version", "include/kubernetes.yml"),
    }
    upstream_tag = expand(
        scalar(include, "k8s-upstream-tag", "include/kubernetes.yml"),
        atoms,
        "include/kubernetes.yml k8s-upstream-tag",
    )
    cni_tag = expand(
        scalar(include, "cni-upstream-tag", "include/kubernetes.yml"),
        atoms,
        "include/kubernetes.yml cni-upstream-tag",
    )
    version = atoms["k8s-version"]

    if not SAFE_VERSION_RE.match(version):
        fail(
            f"derived k8s-version {version!r} is not filename-safe.\n"
            "  It becomes a GitHub release asset name and is parsed back out by\n"
            "  the '@v' wildcard in\n"
            "  files/os/sysupdate.kubernetes.d/70-kubernetes.transfer.",
            "restrict k8s-version to [A-Za-z0-9._~^+-] in include/kubernetes.yml.",
        )

    # Every upstream download URL must be derived, not restated.
    bin_text = read(K8S_BIN)
    urls = source_urls(bin_text)
    for binary in NODE_BINARIES:
        matching = [url for url in urls if url.endswith(f"/{binary}")]
        if not matching:
            fail(
                "elements/kubernetes/kubernetes-bin.bst declares no source 'url:'\n"
                f"  ending in '/{binary}'.\n"
                "  All three node binaries must come from the same pinned release,\n"
                "  or kubeadm, the kubelet and kubectl can disagree on version.",
                f"restore the pinned dl.k8s.io download URL for {binary}.",
            )
        for url in matching:
            if "%{k8s-upstream-tag}" not in url:
                fail(
                    "elements/kubernetes/kubernetes-bin.bst hardcodes the upstream\n"
                    f"  Kubernetes release tag:\n  url: {url}\n"
                    "  A hardcoded tag drifts from include/kubernetes.yml, so the\n"
                    "  binaries and the version stamped into the sysext can\n"
                    "  disagree.",
                    "use 'url: k8s:%{k8s-upstream-tag}/bin/linux/amd64/"
                    f"{binary}'.",
                )

    cni_text = read(CNI_BIN)
    cni_urls = source_urls(cni_text)
    if not cni_urls:
        fail(
            "elements/kubernetes/cni-plugins.bst declares no source 'url:'.",
            "restore the pinned upstream CNI plugins release URL.",
        )
    for url in cni_urls:
        if "%{cni-upstream-tag}" not in url:
            fail(
                "elements/kubernetes/cni-plugins.bst hardcodes the upstream CNI\n"
                f"  plugins release tag:\n  url: {url}\n"
                "  A hardcoded tag drifts from include/kubernetes.yml, so the\n"
                "  plugins on disk and the kubernetes-cni-version stamp the\n"
                "  sysext advertises can disagree.",
                "use 'url: github:containernetworking/plugins/releases/download/"
                "%{cni-upstream-tag}/cni-plugins-linux-amd64-"
                "%{cni-upstream-tag}.tgz'.",
            )

    # The asset filename must be on the Kubernetes axis, not the OS release axis.
    sysext_text = read(K8S_SYSEXT)
    fname_match = re.search(r'^\s*FNAME="([^"]+)"\s*$', sysext_text, re.MULTILINE)
    if not fname_match:
        fail(
            'elements/oci/kubernetes-sysext.bst declares no FNAME="..." asset name.',
            "restore the sysext asset filename assignment.",
        )
    fname_expr = fname_match.group(1)
    if "%{release-version}" in fname_expr:
        fail(
            "elements/oci/kubernetes-sysext.bst names the Kubernetes sysext on the\n"
            f"  OS release axis: FNAME=\"{fname_expr}\"\n"
            "  70-kubernetes.transfer reads this filename as the version of the\n"
            "  Kubernetes it delivers.",
            'use FNAME="kubernetes-%{k8s-version}.raw".',
        )
    if "%{k8s-version}" not in fname_expr:
        fail(
            "elements/oci/kubernetes-sysext.bst does not derive the sysext asset\n"
            f"  name from the pinned Kubernetes version: FNAME=\"{fname_expr}\"",
            'use FNAME="kubernetes-%{k8s-version}.raw".',
        )

    # VERSION_ID must be generated, so sysext status matches the asset.
    if 'echo "VERSION_ID=%{k8s-version}"' not in sysext_text:
        fail(
            "elements/oci/kubernetes-sysext.bst does not generate VERSION_ID= from\n"
            "  %{k8s-version}, so `systemd-sysext status` can disagree with the\n"
            "  asset filename an operator sees on disk.",
            'append \'VERSION_ID=%{k8s-version}\' to the staged '
            "extension-release.kubernetes.",
        )

    # The on-image version stamps must be generated from the same atoms.
    for stamp, atom in (
        ("kubernetes-version", "%{k8s-version}"),
        ("kubernetes-cni-version", "%{cni-version}"),
    ):
        if f'echo "{atom}" > sysext/usr/local/share/{stamp}' not in sysext_text:
            fail(
                f"elements/oci/kubernetes-sysext.bst does not generate\n"
                f"  /usr/local/share/{stamp} from {atom}.\n"
                "  That file is what a merged /usr reports as the delivered\n"
                "  version; a stale or absent stamp misreports the running node.",
                f'write the stamp with \'echo "{atom}" > '
                f"sysext/usr/local/share/{stamp}'.",
            )

    ext_text = read(EXTENSION_RELEASE)
    stale = [
        line
        for line in ext_text.splitlines()
        if line.strip().startswith("VERSION_ID=")
    ]
    if stale:
        fail(
            "files/kubernetes/sysext/extension-release.kubernetes hardcodes a\n"
            f"  version:\n  {stale[0]}\n"
            "  It is appended at build time from %{k8s-version}; a literal here\n"
            "  is a second, silently-winning source of truth.",
            "delete the VERSION_ID= line from "
            "files/kubernetes/sysext/extension-release.kubernetes.",
        )

    for path in (K8S_BIN, CNI_BIN, K8S_SYSEXT, EXTENSION_RELEASE):
        for line in read(path).splitlines():
            if line.lstrip().startswith("#"):
                continue
            found = LITERAL_VERSION_RE.search(line)
            if found:
                fail(
                    f"{path.relative_to(ROOT)} restates a literal Kubernetes or CNI\n"
                    f"  version:\n  {line.strip()}\n"
                    f"  Literal: {found.group(0)}",
                    "read the version from include/kubernetes.yml via "
                    "%{k8s-upstream-tag}, %{cni-upstream-tag}, %{k8s-version} or "
                    "%{cni-version}.",
                )

    # The produced asset name must satisfy the sysupdate transfer pattern.
    asset = fname_expr.replace("%{k8s-version}", version) + ".zst"
    transfer_text = read(TRANSFER)
    pattern_match = re.search(
        r"^\s*MatchPattern=(\S*@v\S*\.zst)\s*$", transfer_text, re.MULTILINE
    )
    if not pattern_match:
        fail(
            "files/os/sysupdate.kubernetes.d/70-kubernetes.transfer declares no\n"
            "  [Source] MatchPattern=...@v....zst.",
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
            "the version systemd-sysupdate would read from the Kubernetes sysext\n"
            "  asset name is not the pinned Kubernetes version:\n"
            f"  built asset    : {asset}\n"
            f"  MatchPattern   : {pattern}\n"
            f"  '@v' captures  : {captured!r}\n"
            f"  k8s-version    : {version!r}\n"
            "  Hosts compare the captured string against the version they have\n"
            "  installed, so a mismatch means Kubernetes updates silently stop.",
            "align FNAME in elements/oci/kubernetes-sysext.bst with MatchPattern "
            "in files/os/sysupdate.kubernetes.d/70-kubernetes.transfer.",
        )

    print(
        f"OK: Kubernetes {upstream_tag} and CNI plugins {cni_tag} pinned in "
        f"include/kubernetes.yml; asset {asset} matches {pattern} and "
        f"VERSION_ID={version}."
    )


if __name__ == "__main__":
    main()
