#!/usr/bin/env python3
"""Track patch releases of the upstream binaries pinned by version + sha256.

A component is one upstream version plus every sha256 pin derived from it. The
two move in one change: a new version with an old checksum is a broken
BuildStream source ref.

  component        version                                  sha256 pins
  kubernetes       include/kubeadm.yml kubernetes-version   kubelet, kubeadm, kubectl  ref: in
  cri-tools        include/kubeadm.yml crictl-version       crictl tarball             elements/kubeadm/
  containerd       include/kubeadm.yml containerd-version   containerd static tarball  kubeadm-bin.bst
  runc             include/kubeadm.yml runc-version         runc.<arch>
  cni-plugins      include/kubeadm.yml cni-plugins-version  CNI plugins tarball
  k0s              include/k0s.yml k0s-k8s-version and      k0s binary                 ref: in
                   k0s-patch                                                           elements/k0s/k0s-bin.bst
  nvidia-open-595  include/nvidia.yml                       NVIDIA-Linux-x86_64-       nvidia-open-595-sha256
                   nvidia-open-595-version                  <version>.run              in include/nvidia.yml
  oras             Justfile oras_image tag                  setup-oras url + checksum in .github/workflows/*.yml
  nvidia-container-toolkit
                   include/nvidia-container-toolkit.yml     the release tag's commit   nvidia-container-toolkit-
                   nvidia-container-toolkit-version                                    commit in the same include
  iana-etc         elements/bluefin-server/iana-etc.bst     iana-etc-<date>.tar.gz     ref: in the same element
                   iana-etc-version

The .bst pins cover every architecture the element fetches: the top-level
amd64 sources and the arm64 ones under `(?): arch == "aarch64"`. Every
`url:` line carrying the component's marker is a pin, wherever it sits, so a
bump refreshes all architectures at once, and a release counts as a candidate
only when every architecture's asset and checksum file is attached. ORAS is
CI tooling and pinned for amd64 runners only. An NVIDIA driver flavour is
x86_64 only, and its sha256 is an atom next to its version, which the
element's `ref:` reads. The NVIDIA Container Toolkit is built from source
fetched with git, and NVIDIA publishes no checksum for any archive of it, so
its pin is the release tag's commit instead of a sha256
(GitTagComponent). iana-etc (/etc/protocols and /etc/services) is a data
snapshot tagged with its date, so it has no series: every newer release is
proposed (SnapshotComponent).

check   Newest release of each component inside its pinned MAJOR.MINOR series:
        Kubernetes from dl.k8s.io/release/stable-X.Y.txt, an NVIDIA driver
        flavour from the directory index at
        download.nvidia.com/XFree86/Linux-x86_64/ (its series is its driver
        branch; a newer release counts once its .run and .run.sha256sum both
        answer a HEAD request), the rest from the project's GitHub releases
        (iana-etc: the newest date tag, whatever the series).
        Drafts, prereleases and releases that lack the pinned assets do not
        count.
apply   Moves one component to a version (default: the newest in its series)
        and rewrites every pin derived from it. Each sha256 is read from the
        checksum file the project publishes next to the asset, then confirmed
        by downloading the asset and hashing it; a tag's commit must be the
        same in the GitHub API and on the git remote. Nothing is written
        unless every pin verifies.

Only patch releases are proposed automatically. A minor bump is a decision: the
kubeadm payload follows the minor of the cluster it joins
(docs/skills/kubeadm-sysext.md). Make it by hand with
`apply COMPONENT --version X.Y.Z`, which runs the same verification. An NVIDIA
flavour never leaves its driver branch; a new branch is a new flavour
(docs/skills/nvidia-sysext.md).

Why not Renovate: a regex manager needs the version and its digest in one
match, but here the version lives in include/*.yml or the Justfile and the
digests in elements/*.bst or a workflow. One Kubernetes version feeds three
dl.k8s.io checksums, which no Renovate datasource computes, and the k0s version
is split into two atoms. postUpgradeTasks, which could fetch checksums, are
blocked on the hosted Renovate app.

Why not `bst source track`: it re-downloads every source of the element instead
of the bumped component's, takes whatever bytes it gets as the new ref instead
of checking the upstream checksum, and writes the element back in its own YAML
layout (it re-indents every list in elements/k0s/k0s-bin.bst). BuildStream
still checks each ref against the bytes when the pull request's build fetches
the sources.

Stdlib only. GITHUB_TOKEN or GH_TOKEN, if set, is sent to api.github.com only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from http.client import HTTPResponse
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parents[2]
TIMEOUT = 60
MAX_RELEASE_PAGES = 20

URL_LINE_RE = re.compile(r"^\s*(?:-\s+)?url:\s*(?P<url>\S+)\s*$")
VARIABLE_RE = re.compile(r'^\s+(?P<name>[A-Za-z][\w-]*):\s*"(?P<value>[^"]*)"', re.MULTILINE)
ALIAS_RE = re.compile(r"^\s+(?P<name>[A-Za-z][\w-]*):\s*(?P<url>https://\S+)\s*$", re.MULTILINE)
SUMS_LINE_RE = re.compile(r"^(?P<sha>[0-9a-fA-F]{64})(?:\s+\*?(?P<name>\S+))?$")


class TrackError(Exception):
    pass


class NotFound(TrackError):
    pass


def _open(url: str, method: str = "GET") -> HTTPResponse:
    headers = {"User-Agent": "projectbluefin-server-track-binaries"}
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            # Never on downloads: release assets redirect to object storage,
            # which must not see the token.
            headers["Authorization"] = f"Bearer {token}"
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers, method=method), timeout=TIMEOUT)
    except urllib.error.HTTPError as err:
        raise (NotFound if err.code == 404 else TrackError)(f"{method} {url}: HTTP {err.code}") from None
    except urllib.error.URLError as err:
        raise TrackError(f"{method} {url}: {err.reason}") from None


def _get(url: str) -> bytes:
    with _open(url) as response:
        return response.read()


def _published(url: str) -> bool:
    """Whether `url` is there, asked with HEAD. Only a 404 means no; other failures raise."""
    try:
        with _open(url, "HEAD"):
            return True
    except NotFound:
        return False


def _download_sha256(url: str) -> str:
    digest = hashlib.sha256()
    with _open(url) as response:
        while chunk := response.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


class Tree:
    """Repository files, read on first use and written back only by save()."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._text: dict[str, str] = {}
        self._original: dict[str, str] = {}

    def __getitem__(self, path: str) -> str:
        if path not in self._text:
            try:
                text = (self.root / path).read_text(encoding="utf-8")
            except FileNotFoundError:
                raise TrackError(f"{path}: file not found") from None
            self._text[path] = self._original[path] = text
        return self._text[path]

    def __setitem__(self, path: str, text: str) -> None:
        self[path]
        self._text[path] = text

    def copy(self) -> Tree:
        other = Tree(self.root)
        other._text = dict(self._text)
        other._original = dict(self._original)
        return other

    def glob(self, *patterns: str) -> list[str]:
        return sorted({p.relative_to(self.root).as_posix() for pattern in patterns for p in self.root.glob(pattern)})

    def save(self) -> list[str]:
        changed = sorted(path for path, text in self._text.items() if text != self._original[path])
        for path in changed:
            (self.root / path).write_text(self._text[path], encoding="utf-8")
        return changed


@dataclass(frozen=True)
class Pin:
    """A sha256 on the `key:` line in the same mapping as `url: anchor` in `path`.

    `url` is what the pin pins and `sums` where its value is read: a checksum
    file for a sha256, the GitHub API's commit for a git tag (GitTagComponent).
    """

    path: str
    anchor: str
    key: str
    url: str
    sums: str
    # When True, `anchor` is unused: the sha256 is the one `key:` line in
    # `path` (an include atom like `nvidia-open-595-sha256:`), not a
    # source's `ref:`.
    standalone_key: bool = False

    @property
    def asset(self) -> str:
        return urllib.parse.unquote(self.url.rsplit("/", 1)[1])


def _key_in_mapping(lines: list[str], start: int, column: int, key: str) -> int | None:
    for j in range(start + 1, len(lines)):
        text = lines[j].strip()
        if not text or text.startswith("#"):
            continue
        indent = len(lines[j]) - len(lines[j].lstrip())
        if indent < column:
            return None
        if indent == column and re.match(rf"{re.escape(key)}:\s*\S+\s*$", text):
            return j
    return None


def _checksum_lines(lines: list[str], pin: Pin) -> list[int]:
    """Line numbers of `pin.key:` for every `url: pin.anchor` line; each must have one."""
    if pin.standalone_key:
        found = [i for i, line in enumerate(lines) if re.match(rf"^\s*{re.escape(pin.key)}:\s*\S+\s*$", line)]
        if len(found) != 1:
            raise TrackError(f"{pin.path}: expected exactly one `{pin.key}:` line, found {len(found)}")
        return found
    found = []
    for i, line in enumerate(lines):
        match = URL_LINE_RE.match(line)
        if not match or match["url"] != pin.anchor:
            continue
        j = _key_in_mapping(lines, i, line.index("url:"), pin.key)
        if j is None:
            raise TrackError(f"{pin.path}: no `{pin.key}:` in the mapping of `url: {pin.anchor}`")
        found.append(j)
    if not found:
        raise TrackError(f"{pin.path}: no `url: {pin.anchor}`")
    return found


def read_pin(tree: Tree, pin: Pin) -> str:
    lines = tree[pin.path].splitlines(keepends=True)
    raw = {lines[i].split(":", 1)[1].strip() for i in _checksum_lines(lines, pin)}
    if len(raw) != 1:
        raise TrackError(f"{pin.path}: `url: {pin.anchor}` is pinned to different checksums: {sorted(raw)}")
    # The .bst elements pin `ref:` to a bare sha256 (no quotes). The
    # include files pin atoms (e.g. `nvidia-open-595-sha256:`) to a YAML
    # double-quoted string. Strip a uniform pair of quotes if present so
    # the existing SUMS_LINE_RE match keeps working.
    value = raw.pop()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        value = value[1:-1]
    return value


def write_pin(tree: Tree, pin: Pin, sha256: str) -> None:
    lines = tree[pin.path].splitlines(keepends=True)
    value = re.compile(rf"^(\s*{re.escape(pin.key)}:\s*)(\S+)")
    for i in _checksum_lines(lines, pin):
        lines[i] = value.sub(lambda m: m[1] + (f'"{sha256}"' if m[2].startswith('"') else sha256), lines[i], count=1)
    tree[pin.path] = "".join(lines)


def _variable(tree: Tree, path: str, name: str) -> re.Match:
    matches = [m for m in VARIABLE_RE.finditer(tree[path]) if m["name"] == name]
    if len(matches) != 1:
        raise TrackError(f'{path}: expected exactly one `{name}: "..."`, found {len(matches)}')
    return matches[0]


def _expand(template: str, variables: dict[str, str], aliases: dict[str, str], where: str) -> str:
    """Resolve a source url the way BuildStream does: `%{...}` variables, then the alias."""
    for _ in range(len(variables) + 1):
        refs = re.findall(r"%\{([A-Za-z][\w-]*)\}", template)
        if not refs:
            break
        for ref in refs:
            if ref not in variables:
                raise TrackError(f"{where}: `{template}` uses undefined variable %{{{ref}}}")
            template = template.replace("%{" + ref + "}", variables[ref])
    else:
        raise TrackError(f"{where}: circular variable reference in `{template}`")
    alias, _, rest = template.partition(":")
    if alias in aliases:
        template = aliases[alias] + rest
    if not template.startswith("https://"):
        raise TrackError(f"{where}: `{template}` does not resolve to an https:// URL")
    return template


def _numbers(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def _series(version: str) -> str:
    return ".".join(str(n) for n in _numbers(version)[:2])


class Component:
    name: str
    repo: str
    # Checksum file URL; {url} is the asset URL, {dir} its directory.
    sums: str
    stable_channel = ""
    version_re = r"(\d+\.\d+\.\d+)"
    # A GitHub release tag is this prefix plus the version.
    tag_prefix = "v"
    # How to go past the pinned series, for the pull request body.
    beyond_series = "a minor bump is a manual `.github/scripts/track-binaries.py apply {name} --version ...`."

    def current(self, tree: Tree) -> str:
        raise NotImplementedError

    def set_version(self, tree: Tree, version: str) -> None:
        raise NotImplementedError

    def pins(self, tree: Tree) -> list[Pin]:
        raise NotImplementedError

    def series(self, version: str) -> str:
        return _series(version)

    def candidates(self, tree: Tree, series: str) -> list[str]:
        """Releases in `series`: the stable channel's, or every GitHub release with its pinned assets."""
        if self.stable_channel:
            url = self.stable_channel.format(series=series)
            text = _get(url).decode().strip()
            if not re.fullmatch(rf"v{re.escape(series)}\.\d+", text):
                raise TrackError(f"{url} says `{text}`, not a {series}.x release")
            return [text[1:]]
        found = []
        prefix = f"https://github.com/{self.repo}/releases/download/"
        for release in _github_releases(self.repo):
            tag = release.get("tag_name", "")
            if release.get("draft") or release.get("prerelease") or not tag.startswith(self.tag_prefix):
                continue
            version = tag[len(self.tag_prefix):]
            if not re.fullmatch(self.version_re, version) or self.series(version) != series:
                continue
            # The pinned assets must be attached already: a release can be
            # published while its assets are still uploading.
            names = {asset["name"] for asset in release.get("assets", [])}
            wanted = {
                urllib.parse.unquote(url.rsplit("/", 1)[1])
                for pin in _pins_at(self, tree, version)
                for url in (pin.url, pin.sums)
                if url.startswith(prefix)
            }
            if wanted <= names:
                found.append(version)
        return found

    def parse(self, version: str) -> tuple[str, ...]:
        match = re.fullmatch(self.version_re, version)
        if not match:
            raise TrackError(f"{self.name}: `{version}` does not match {self.version_re}")
        return match.groups()

    def _sums(self, url: str, version: str) -> str:
        return self.sums.format(url=url, dir=url.rsplit("/", 1)[0], version=version)

    def notes(self, version: str) -> str:
        return f"https://github.com/{self.repo}/releases/tag/{urllib.parse.quote(self.tag_prefix + version)}"

    def headline(self, old: str, new: str) -> str:
        """First line of the pull request body."""
        series = self.series(new)
        if self.series(old) == series:
            return f"Patch release of **{self.name}** in the pinned `{series}` series: `{old}` → `{new}`."
        return f"Moves **{self.name}** from `{old}` to `{new}`, a series change."

    def policy(self) -> str:
        """What the tracker proposes on its own, for the pull request body."""
        return f"Only patch releases inside the pinned series are proposed; {self.beyond_series.format(name=self.name)}"

    # What a pin holds, for the pull request body.
    pin_label = "sha256"

    def verify(self, tree: Tree) -> list[Change]:
        """Read each pin of the version `tree` is set to from upstream, confirm it and write it to `tree`.

        The sha256 comes from the checksum file the project publishes next to
        the asset and must match the downloaded asset's.
        """
        sums: dict[str, str] = {}
        hashed: dict[str, str] = {}
        changes = []
        for pin in self.pins(tree):
            if pin.sums not in sums:
                sums[pin.sums] = _get(pin.sums).decode("utf-8", "replace")
            sha = published_sha256(sums[pin.sums], pin.asset, pin.sums)
            if pin.url not in hashed:
                hashed[pin.url] = _download_sha256(pin.url)
            if hashed[pin.url] != sha:
                raise TrackError(f"{pin.url} hashes to {hashed[pin.url]}, but {pin.sums} says {sha}")
            changes.append(Change(pin, read_pin(tree, pin), sha))
            write_pin(tree, pin, sha)
        return changes

    def evidence(self, result: Result) -> list[str]:
        return [
            "Every sha256 comes from the checksum file upstream publishes next to the",
            "asset, and matched the sha256 of the downloaded asset:",
            "",
            *[f"- {url}" for url in dict.fromkeys(change.pin.sums for change in result.changes)],
        ]


class BstComponent(Component):
    """Version atoms in a BuildStream include; sha256 refs on one element's sources."""

    # Whether the element pins every architecture BuildStream fetches, so the
    # "amd64 == arm64" invariant and its dedicated tests apply. Components
    # whose upstream only ships one architecture (for example the NVIDIA
    # driver, which is x86_64 only) override this to False.
    multi_arch = True

    def __init__(self, name: str, repo: str, sums: str, include: str, variables: tuple[str, ...], element: str,
                 marker: str, stable_channel: str = "", version_re: str | None = None, version_fmt: str = "{0}",
                 element_variables: Iterable[str] = ()) -> None:
        self.name, self.repo, self.sums, self.stable_channel = name, repo, sums, stable_channel
        self.include, self.variables, self.element, self.marker = include, variables, element, marker
        self.version_re = version_re or Component.version_re
        self.version_fmt = version_fmt
        # Variables the element file sets (e.g. nvidia-version: "%{nvidia-open-595-version}")
        # that the source URL template depends on. They are merged into the variable
        # map at expansion time so URLs that interpolate local element variables
        # resolve. Leave empty unless the URL needs an atom that lives in the
        # element, not the include.
        self.element_variables = tuple(element_variables)

    def current(self, tree: Tree) -> str:
        return self.version_fmt.format(*(_variable(tree, self.include, v)["value"] for v in self.variables))

    def set_version(self, tree: Tree, version: str) -> None:
        for name, value in zip(self.variables, self.parse(version), strict=True):
            match = _variable(tree, self.include, name)
            text = tree[self.include]
            tree[self.include] = text[: match.start("value")] + value + text[match.end("value") :]

    def pins(self, tree: Tree) -> list[Pin]:
        variables = {m["name"]: m["value"] for m in VARIABLE_RE.finditer(tree[self.include])}
        # Element-defined variables override include-defined ones by name. Only the
        # subset named in `element_variables` is read; reading every variable in
        # the element would add strip-binaries, etc., that the URL never uses
        # and would silently mask include variables of the same name.
        for name in self.element_variables:
            variables[name] = _variable(tree, self.element, name)["value"]
        aliases = {m["name"]: m["url"] for m in ALIAS_RE.finditer(tree["include/aliases.yml"])}
        version = self.current(tree)
        pins = []
        for line in tree[self.element].splitlines():
            match = URL_LINE_RE.match(line)
            if match and self.marker in match["url"]:
                url = _expand(match["url"], variables, aliases, self.element)
                pins.append(Pin(self.element, match["url"], "ref", url, self._sums(url, version)))
        if not pins:
            raise TrackError(f"{self.element}: no source url contains {self.marker}")
        return pins


class NvidiaDriverComponent(BstComponent):
    """One NVIDIA driver flavour, nvidia-open-<branch>, tracked inside its branch.

    The version and the .run's sha256 are the flavour's two atoms in
    include/nvidia.yml; the element's `ref:` reads the sha256 atom. NVIDIA
    publishes each release as a directory under INDEX holding
    NVIDIA-Linux-x86_64-<version>.run and <file>.sha256sum. A newer release
    of the branch counts once both answer a HEAD request: `check` never
    downloads a .run, `apply` downloads and hashes the one it moves to.
    """

    INDEX = "https://download.nvidia.com/XFree86/Linux-x86_64/"
    DIR_RE = re.compile(r"""href=["']([^"'/]+)/["']""")
    multi_arch = False
    beyond_series = "a new driver branch is a new flavour (docs/skills/nvidia-sysext.md)."

    def __init__(self, flavour: str):
        branch = flavour.removeprefix("nvidia-open-")
        super().__init__(flavour, "", "{url}.sha256sum", include="include/nvidia.yml",
                         variables=(f"{flavour}-version",), element=f"elements/nvidia/{flavour}.bst",
                         marker="%{nvidia-version}", element_variables=("nvidia-version",),
                         version_re=rf"({re.escape(branch)}\.\d+(?:\.\d+)?)")

    def series(self, version: str) -> str:
        return version.split(".", 1)[0]

    def pins(self, tree: Tree) -> list[Pin]:
        pins = super().pins(tree)
        if len(pins) != 1:
            raise TrackError(f"{self.element}: expected one source url with {self.marker}, found {len(pins)}")
        return [Pin(self.include, "", f"{self.name}-sha256", pins[0].url, pins[0].sums, standalone_key=True)]

    def candidates(self, tree: Tree, series: str) -> list[str]:
        current = self.current(tree)
        index = _get(self.INDEX).decode("utf-8", "replace")
        listed = {m[1] for m in self.DIR_RE.finditer(index) if re.fullmatch(self.version_re, m[1])}
        if current not in listed:
            raise TrackError(f"{self.INDEX} does not list the pinned {current}; did its format change?")
        found = []
        for version in sorted(listed, key=_numbers):
            if _numbers(version) <= _numbers(current):
                continue
            (pin,) = _pins_at(self, tree, version)
            if _published(pin.url) and _published(pin.sums):
                found.append(version)
        return found

    def notes(self, version: str) -> str:
        return f"{self.INDEX}{version}/"


class SnapshotComponent(BstComponent):
    """A data snapshot released under its date (YYYYMMDD tag, no "v"), not a semantic version.

    The version atom and the tarball's sha256 live in the element itself.
    There is no series to stay inside: every newer release with its tarball
    and checksum file attached is a candidate, and `apply` takes the newest.
    """

    multi_arch = False
    tag_prefix = ""

    def __init__(self, name: str, repo: str, sums: str, element: str):
        variable = f"{name}-version"
        super().__init__(name, repo, sums, include=element, variables=(variable,), element=element,
                         marker=f"%{{{variable}}}", version_re=r"(\d{8})")

    def series(self, version: str) -> str:
        return "date"

    def headline(self, old: str, new: str) -> str:
        return f"New **{self.name}** snapshot: `{old}` → `{new}`."

    def policy(self) -> str:
        return f"Every newer {self.name} snapshot is proposed; there is no series to stay inside."


class GitTagComponent(Component):
    """A source fetched with git at a release tag, pinned by the tag's commit.

    The version and the commit are two atoms in one include, and the
    element's git_repo `ref:` reads both as `v<version>-0-g<commit>`, so the
    version is written once. Candidates are the project's GitHub releases,
    as for the binaries; a release needs no assets, only its tag.

    No checksum file exists for a git tag, so `apply` asks two upstream
    services for the tag's commit and writes nothing unless they agree: the
    GitHub REST API (commits/refs/tags/<tag>, which peels an annotated tag)
    and the git remote itself (`git ls-remote`, the `^{}` entry of an
    annotated tag or the entry of a lightweight one). The commit id is the
    content address BuildStream fetches by.
    """

    pin_label = "commit"
    COMMIT_RE = re.compile(r"[0-9a-f]{40}")

    def __init__(self, name: str, repo: str, include: str, element: str):
        self.name, self.repo, self.include, self.element = name, repo, include, element
        self.version_variable, self.commit_variable = f"{name}-version", f"{name}-commit"
        self.git_url = f"https://github.com/{repo}.git"

    def current(self, tree: Tree) -> str:
        return _variable(tree, self.include, self.version_variable)["value"]

    def set_version(self, tree: Tree, version: str) -> None:
        (value,) = self.parse(version)
        match = _variable(tree, self.include, self.version_variable)
        text = tree[self.include]
        tree[self.include] = text[: match.start("value")] + value + text[match.end("value") :]

    def ref_template(self) -> str:
        return f"v%{{{self.version_variable}}}-0-g%{{{self.commit_variable}}}"

    def pins(self, tree: Tree) -> list[Pin]:
        variables = {m["name"]: m["value"] for m in VARIABLE_RE.finditer(tree[self.include])}
        aliases = {m["name"]: m["url"] for m in ALIAS_RE.finditer(tree["include/aliases.yml"])}
        anchors = [
            match["url"]
            for match in map(URL_LINE_RE.match, tree[self.element].splitlines())
            if match and _expand(match["url"], variables, aliases, self.element) == self.git_url
        ]
        if len(anchors) != 1:
            raise TrackError(f"{self.element}: expected one source url for {self.git_url}, found {len(anchors)}")
        ref = read_pin(tree, Pin(self.element, anchors[0], "ref", self.git_url, ""))
        if ref != self.ref_template():
            raise TrackError(f"{self.element}: the ref of {anchors[0]} is `{ref}`, not `{self.ref_template()}`")
        tag = urllib.parse.quote(f"v{self.current(tree)}")
        api = f"https://api.github.com/repos/{self.repo}/commits/refs/tags/{tag}"
        return [Pin(self.include, "", self.commit_variable, self.git_url, api, standalone_key=True)]

    def verify(self, tree: Tree) -> list[Change]:
        (pin,) = self.pins(tree)
        tag = f"v{self.current(tree)}"
        from_api = json.loads(_get(pin.sums)).get("sha", "")
        if not self.COMMIT_RE.fullmatch(from_api):
            raise TrackError(f"{pin.sums} gives no commit id for {tag}")
        from_git = _git_tag_commit(pin.url, tag)
        if from_api != from_git:
            raise TrackError(f"{pin.sums} says {tag} is {from_api}, but the git remote {pin.url} says {from_git}")
        change = Change(pin, read_pin(tree, pin), from_api)
        write_pin(tree, pin, from_api)
        return [change]

    def evidence(self, result: Result) -> list[str]:
        tag = f"refs/tags/v{result.new}"
        lines = ["The commit is the one two upstream answers agree on for the tag:", ""]
        for pin, _, _ in result.changes:
            lines += [f"- the GitHub API: {pin.sums}", f"- the git remote: `git ls-remote {pin.url} {tag} '{tag}^{{}}'`"]
        return lines


def _git_tag_commit(url: str, tag: str) -> str:
    """The commit `tag` points to on the git remote at `url`, peeled if the tag is annotated."""
    ref = f"refs/tags/{tag}"
    command = ["git", "ls-remote", url, ref, ref + "^{}"]
    try:
        listing = subprocess.run(command, capture_output=True, text=True, timeout=TIMEOUT, check=True,
                                 env={**os.environ, "GIT_TERMINAL_PROMPT": "0"}).stdout
    except (OSError, subprocess.SubprocessError) as err:
        detail = getattr(err, "stderr", None) or err
        raise TrackError(f"{' '.join(command)}: {str(detail).strip()}") from None
    refs = {}
    for line in listing.splitlines():
        oid, _, name = line.partition("\t")
        refs[name] = oid
    commit = refs.get(ref + "^{}") or refs.get(ref)
    if commit is None:
        raise TrackError(f"{url} has no {ref}")
    if not GitTagComponent.COMMIT_RE.fullmatch(commit):
        raise TrackError(f"{url}: {ref} is `{commit}`, not a commit id")
    return commit


class OrasComponent(Component):
    """The Justfile's ORAS image tag plus every setup-oras url and checksum."""

    name = "oras"
    repo = "oras-project/oras"
    sums = "{dir}/oras_{version}_checksums.txt"
    WORKFLOWS = (".github/workflows/*.yml", ".github/workflows/*.yaml")
    IMAGE_RE = re.compile(r"(?P<head>ghcr\.io/oras-project/oras:v)(?P<version>\d+\.\d+\.\d+)(?![\w.])")
    URL_RE = re.compile(
        r"https://github\.com/oras-project/oras/releases/download/"
        r"v(?P<tag>\d+\.\d+\.\d+)/oras_(?P<version>\d+\.\d+\.\d+)_linux_amd64\.tar\.gz"
    )

    def _sites(self, tree: Tree) -> tuple[list[tuple[str, str]], list[tuple[str, re.Match[str]]]]:
        sites = [("Justfile", m["version"]) for m in self.IMAGE_RE.finditer(tree["Justfile"])]
        if not sites:
            raise TrackError("Justfile: no ghcr.io/oras-project/oras:vX.Y.Z image")
        urls = [(path, m) for path in tree.glob(*self.WORKFLOWS) for m in self.URL_RE.finditer(tree[path])]
        if not urls:
            raise TrackError(".github/workflows: no setup-oras release url")
        for path, match in urls:
            sites += [(path, match["tag"]), (path, match["version"])]
        return sites, urls

    def current(self, tree: Tree) -> str:
        sites, _ = self._sites(tree)
        versions = {version for _, version in sites}
        if len(versions) != 1:
            pinned = ", ".join(f"{path}: {version}" for path, version in sorted(set(sites)))
            raise TrackError(f"ORAS pins disagree ({pinned}); make them one version first")
        return versions.pop()

    def set_version(self, tree: Tree, version: str) -> None:
        self.parse(version)
        _, urls = self._sites(tree)
        tree["Justfile"] = self.IMAGE_RE.sub(lambda m: m["head"] + version, tree["Justfile"])
        new = f"https://github.com/oras-project/oras/releases/download/v{version}/oras_{version}_linux_amd64.tar.gz"
        for path in sorted({path for path, _ in urls}):
            tree[path] = self.URL_RE.sub(new, tree[path])

    def pins(self, tree: Tree) -> list[Pin]:
        version = self.current(tree)
        _, urls = self._sites(tree)
        return [
            Pin(path, url, "checksum", url, self._sums(url, version))
            for path, url in sorted({(path, m[0]) for path, m in urls})
        ]


KUBEADM = dict(include="include/kubeadm.yml", element="elements/kubeadm/kubeadm-bin.bst")
COMPONENTS: dict[str, Component] = {
    c.name: c
    for c in (
        BstComponent("kubernetes", "kubernetes/kubernetes", "{url}.sha256",
                     variables=("kubernetes-version",), marker="%{kubernetes-version}",
                     stable_channel="https://dl.k8s.io/release/stable-{series}.txt", **KUBEADM),
        BstComponent("cri-tools", "kubernetes-sigs/cri-tools", "{url}.sha256",
                     variables=("crictl-version",), marker="%{crictl-version}", **KUBEADM),
        BstComponent("containerd", "containerd/containerd", "{url}.sha256sum",
                     variables=("containerd-version",), marker="%{containerd-version}", **KUBEADM),
        BstComponent("runc", "opencontainers/runc", "{dir}/runc.sha256sum",
                     variables=("runc-version",), marker="%{runc-version}", **KUBEADM),
        BstComponent("cni-plugins", "containernetworking/plugins", "{url}.sha256",
                     variables=("cni-plugins-version",), marker="%{cni-plugins-version}", **KUBEADM),
        BstComponent("k0s", "k0sproject/k0s", "{dir}/sha256sums.txt",
                     include="include/k0s.yml", variables=("k0s-k8s-version", "k0s-patch"),
                     element="elements/k0s/k0s-bin.bst", marker="%{k0s-upstream-tag}",
                     version_re=r"(\d+\.\d+\.\d+)\+k0s\.(\d+)", version_fmt="{0}+k0s.{1}"),
        NvidiaDriverComponent("nvidia-open-595"),
        SnapshotComponent("iana-etc", "Mic92/iana-etc", "{url}.sha256",
                          element="elements/bluefin-server/iana-etc.bst"),
        GitTagComponent("nvidia-container-toolkit", "NVIDIA/nvidia-container-toolkit",
                        include="include/nvidia-container-toolkit.yml",
                        element="elements/nvidia/nvidia-container-toolkit.bst"),
        OrasComponent(),
    )
}


def _pins_at(component: Component, tree: Tree, version: str) -> list[Pin]:
    scratch = tree.copy()
    component.set_version(scratch, version)
    return component.pins(scratch)


def _github_releases(repo: str) -> list[dict]:
    releases = []
    for page in range(1, MAX_RELEASE_PAGES + 1):
        batch = json.loads(_get(f"https://api.github.com/repos/{repo}/releases?per_page=100&page={page}"))
        releases += batch
        if len(batch) < 100:
            return releases
    raise TrackError(f"{repo}: more than {MAX_RELEASE_PAGES * 100} releases")


def newest(component: Component, tree: Tree) -> str:
    """Newest release in the pinned series, or the current version if none is newer."""
    current = component.current(tree)
    return max([current, *component.candidates(tree, component.series(current))], key=_numbers)


def published_sha256(text: str, asset: str, url: str) -> str:
    """The sha256 a checksum file gives for `asset`.

    Accepts a bare digest (dl.k8s.io, cri-tools) or `digest [*]name` lines
    (sha256sum output, also inside runc's PGP-signed file).
    """
    named: dict[str, set[str]] = {}
    bare = []
    for line in text.splitlines():
        match = SUMS_LINE_RE.match(line.strip())
        if not match:
            continue
        if match["name"]:
            named.setdefault(match["name"].rsplit("/", 1)[-1], set()).add(match["sha"].lower())
        else:
            bare.append(match["sha"].lower())
    if named:
        digests = named.get(asset, set())
        if len(digests) != 1:
            raise TrackError(f"{url} lists {len(digests)} sha256 for {asset}")
        return digests.pop()
    if len(bare) == 1:
        return bare[0]
    raise TrackError(f"{url} is not a sha256 checksum file for {asset}")


class Change(NamedTuple):
    pin: Pin
    before: str
    after: str


@dataclass
class Result:
    component: Component
    old: str
    new: str
    changes: list[Change]
    files: list[str]
    mentions: list[str]


def apply(root: Path, name: str, version: str | None = None) -> Result | None:
    """Move `name` to `version` (default: newest in series) and rewrite its pins.

    Returns None when no version is given and the pin is already the newest.
    """
    component = COMPONENTS[name]
    tree = Tree(root)
    old = component.current(tree)
    new = version or newest(component, tree)
    if version is None and new == old:
        return None
    component.set_version(tree, new)
    changes = component.verify(tree)
    files = tree.save()
    stale = re.compile(rf"(?<![\d.]){re.escape(old)}(?!\d)")
    mentions = [
        f"{path}:{number}: {line.strip()}"
        for path in files
        for number, line in enumerate(tree[path].splitlines(), 1)
        if old != new and stale.search(line)
    ]
    return Result(component, old, new, changes, files, mentions)


def summary(result: Result) -> str:
    component, old, new = result.component, result.old, result.new
    lines = [component.headline(old, new), "", f"Release notes: {component.notes(new)}", "", f"| File | Asset | {component.pin_label} |", "| --- | --- | --- |"]
    for pin, before, after in result.changes:
        was = "unchanged" if before == after else f"was `{before}`"
        lines.append(f"| `{pin.path}` | [`{pin.asset}`]({pin.url}) | `{after}` ({was}) |")
    lines += ["", *component.evidence(result)]
    if result.mentions:
        lines += ["", f"These lines of the changed files still mention `{old}`:", ""]
        lines += [f"- `{mention}`" for mention in result.mentions]
    lines += [
        "",
        component.policy(),
        "The tracker regenerates this branch from `main`, so push fixes to a branch",
        "of your own.",
    ]
    return "\n".join(lines) + "\n"


def check(root: Path) -> tuple[list[dict], list[str]]:
    tree = Tree(root)
    rows, errors = [], []
    for name, component in COMPONENTS.items():
        try:
            current = component.current(tree)
            latest = newest(component, tree)
        except TrackError as err:
            errors.append(f"{name}: {err}")
            continue
        rows.append({"component": name, "series": component.series(current), "current": current, "latest": latest})
    return rows, errors


def main(argv: list[str] | None = None, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description="Track patch releases of the pinned upstream binaries.")
    commands = parser.add_subparsers(dest="command", required=True)
    check_cmd = commands.add_parser("check", help="report the newest release in each pinned series")
    check_cmd.add_argument("--json", action="store_true", help="print the pending updates as a JSON list on stdout")
    apply_cmd = commands.add_parser("apply", help="move one component and rewrite its sha256 pins")
    apply_cmd.add_argument("component", choices=COMPONENTS)
    apply_cmd.add_argument("--version", help="target version (default: newest in the pinned series)")
    apply_cmd.add_argument("--summary", type=Path, help="write a Markdown pull request body to this file")
    args = parser.parse_args(argv)

    if args.command == "check":
        rows, errors = check(root)
        table = sys.stderr if args.json else sys.stdout
        width = max(12, *map(len, COMPONENTS))
        print(f"{'component':<{width}} {'series':<6} {'current':<14} {'latest':<14} state", file=table)
        for row in rows:
            state = "update" if row["latest"] != row["current"] else "current"
            print(f"{row['component']:<{width}} {row['series']:<6} {row['current']:<14} {row['latest']:<14} {state}", file=table)
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        if args.json:
            print(json.dumps([row for row in rows if row["latest"] != row["current"]]))
        return 1 if errors else 0

    try:
        result = apply(root, args.component, args.version)
    except TrackError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return 1
    if result is None:
        print(f"{args.component}: already the newest release of its series", file=sys.stderr)
        return 0
    if args.summary:
        args.summary.write_text(summary(result), encoding="utf-8")
    print(f"{args.component}: {result.old} -> {result.new}", file=sys.stderr)
    for path in result.files:
        print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
