#!/usr/bin/env python3
"""Track patch releases of the upstream binaries pinned by version + sha256.

A component is one upstream version plus every sha256 pin derived from it. The
two move in one change: a new version with an old checksum is a broken
BuildStream source ref.

  component    version                                 sha256 pins
  kubernetes   include/kubeadm.yml kubernetes-version  kubelet, kubeadm, kubectl  ref: in
  cri-tools    include/kubeadm.yml crictl-version      crictl tarball             elements/kubeadm/
  containerd   include/kubeadm.yml containerd-version  containerd static tarball  kubeadm-bin.bst
  runc         include/kubeadm.yml runc-version        runc.<arch>
  cni-plugins  include/kubeadm.yml cni-plugins-version CNI plugins tarball
  k0s          include/k0s.yml k0s-k8s-version and     k0s binary                 ref: in
               k0s-patch                                                          elements/k0s/k0s-bin.bst
  oras         Justfile oras_image tag                 setup-oras url + checksum in .github/workflows/*.yml

The .bst pins cover every architecture the element fetches: the top-level
amd64 sources and the arm64 ones under `(?): arch == "aarch64"`. Every
`url:` line carrying the component's marker is a pin, wherever it sits, so a
bump refreshes all architectures at once, and a release counts as a candidate
only when every architecture's asset and checksum file is attached. ORAS is
CI tooling and pinned for amd64 runners only.

check   Newest release of each component inside its pinned MAJOR.MINOR series:
        Kubernetes from dl.k8s.io/release/stable-X.Y.txt, the rest from the
        project's GitHub releases. Drafts, prereleases and releases that lack
        the pinned assets do not count.
apply   Moves one component to a version (default: the newest in its series)
        and rewrites every pin derived from it. Each sha256 is read from the
        checksum file the project publishes next to the asset, then confirmed
        by downloading the asset and hashing it. Nothing is written unless
        every pin verifies.

Only patch releases are proposed automatically. A minor bump is a decision: the
kubeadm payload follows the minor of the cluster it joins
(docs/skills/kubeadm-sysext.md). Make it by hand with
`apply COMPONENT --version X.Y.Z`, which runs the same verification.

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
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
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


def _open(url: str):
    headers = {"User-Agent": "projectbluefin-server-track-binaries"}
    if url.startswith("https://api.github.com/"):
        headers["Accept"] = "application/vnd.github+json"
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            # Never on downloads: release assets redirect to object storage,
            # which must not see the token.
            headers["Authorization"] = f"Bearer {token}"
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=TIMEOUT)
    except urllib.error.HTTPError as err:
        raise TrackError(f"GET {url}: HTTP {err.code}") from None
    except urllib.error.URLError as err:
        raise TrackError(f"GET {url}: {err.reason}") from None


def _get(url: str) -> bytes:
    with _open(url) as response:
        return response.read()


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
    """A sha256 on the `key:` line in the same mapping as `url: anchor` in `path`."""

    path: str
    anchor: str
    key: str
    url: str
    sums: str

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
    values = {lines[i].split(":", 1)[1].strip() for i in _checksum_lines(lines, pin)}
    if len(values) != 1:
        raise TrackError(f"{pin.path}: `url: {pin.anchor}` is pinned to different checksums: {sorted(values)}")
    return values.pop()


def write_pin(tree: Tree, pin: Pin, sha256: str) -> None:
    lines = tree[pin.path].splitlines(keepends=True)
    value = re.compile(rf"^(\s*{re.escape(pin.key)}:\s*)\S+")
    for i in _checksum_lines(lines, pin):
        lines[i] = value.sub(lambda m: m[1] + sha256, lines[i], count=1)
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

    def current(self, tree: Tree) -> str:
        raise NotImplementedError

    def set_version(self, tree: Tree, version: str) -> None:
        raise NotImplementedError

    def pins(self, tree: Tree) -> list[Pin]:
        raise NotImplementedError

    def parse(self, version: str) -> tuple[str, ...]:
        match = re.fullmatch(self.version_re, version)
        if not match:
            raise TrackError(f"{self.name}: `{version}` does not match {self.version_re}")
        return match.groups()

    def _sums(self, url: str, version: str) -> str:
        return self.sums.format(url=url, dir=url.rsplit("/", 1)[0], version=version)

    def notes(self, version: str) -> str:
        return f"https://github.com/{self.repo}/releases/tag/{urllib.parse.quote('v' + version)}"


class BstComponent(Component):
    """Version atoms in a BuildStream include; sha256 refs on one element's sources."""

    def __init__(self, name, repo, sums, include, variables, element, marker,
                 stable_channel="", version_re=None, version_fmt="{0}"):
        self.name, self.repo, self.sums, self.stable_channel = name, repo, sums, stable_channel
        self.include, self.variables, self.element, self.marker = include, variables, element, marker
        self.version_re = version_re or Component.version_re
        self.version_fmt = version_fmt

    def current(self, tree):
        return self.version_fmt.format(*(_variable(tree, self.include, v)["value"] for v in self.variables))

    def set_version(self, tree, version):
        for name, value in zip(self.variables, self.parse(version)):
            match = _variable(tree, self.include, name)
            text = tree[self.include]
            tree[self.include] = text[: match.start("value")] + value + text[match.end("value") :]

    def pins(self, tree):
        variables = {m["name"]: m["value"] for m in VARIABLE_RE.finditer(tree[self.include])}
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

    def _sites(self, tree):
        sites = [("Justfile", m["version"]) for m in self.IMAGE_RE.finditer(tree["Justfile"])]
        if not sites:
            raise TrackError("Justfile: no ghcr.io/oras-project/oras:vX.Y.Z image")
        urls = [(path, m) for path in tree.glob(*self.WORKFLOWS) for m in self.URL_RE.finditer(tree[path])]
        if not urls:
            raise TrackError(".github/workflows: no setup-oras release url")
        for path, match in urls:
            sites += [(path, match["tag"]), (path, match["version"])]
        return sites, urls

    def current(self, tree):
        sites, _ = self._sites(tree)
        versions = {version for _, version in sites}
        if len(versions) != 1:
            pinned = ", ".join(f"{path}: {version}" for path, version in sorted(set(sites)))
            raise TrackError(f"ORAS pins disagree ({pinned}); make them one version first")
        return versions.pop()

    def set_version(self, tree, version):
        self.parse(version)
        _, urls = self._sites(tree)
        tree["Justfile"] = self.IMAGE_RE.sub(lambda m: m["head"] + version, tree["Justfile"])
        new = f"https://github.com/oras-project/oras/releases/download/v{version}/oras_{version}_linux_amd64.tar.gz"
        for path in sorted({path for path, _ in urls}):
            tree[path] = self.URL_RE.sub(new, tree[path])

    def pins(self, tree):
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


def _candidates(component: Component, tree: Tree, series: str) -> list[str]:
    if component.stable_channel:
        url = component.stable_channel.format(series=series)
        text = _get(url).decode().strip()
        if not re.fullmatch(rf"v{re.escape(series)}\.\d+", text):
            raise TrackError(f"{url} says `{text}`, not a {series}.x release")
        return [text[1:]]
    found = []
    prefix = f"https://github.com/{component.repo}/releases/download/"
    for release in _github_releases(component.repo):
        tag = release.get("tag_name", "")
        if release.get("draft") or release.get("prerelease") or not tag.startswith("v"):
            continue
        version = tag[1:]
        if not re.fullmatch(component.version_re, version) or _series(version) != series:
            continue
        # The pinned assets must be attached already: a release can be
        # published while its assets are still uploading.
        names = {asset["name"] for asset in release.get("assets", [])}
        wanted = {
            urllib.parse.unquote(url.rsplit("/", 1)[1])
            for pin in _pins_at(component, tree, version)
            for url in (pin.url, pin.sums)
            if url.startswith(prefix)
        }
        if wanted <= names:
            found.append(version)
    return found


def newest(component: Component, tree: Tree) -> str:
    """Newest release in the pinned series, or the current version if none is newer."""
    current = component.current(tree)
    return max([current, *_candidates(component, tree, _series(current))], key=_numbers)


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
    sums: dict[str, str] = {}
    hashed: dict[str, str] = {}
    changes = []
    for pin in component.pins(tree):
        if pin.sums not in sums:
            sums[pin.sums] = _get(pin.sums).decode("utf-8", "replace")
        sha = published_sha256(sums[pin.sums], pin.asset, pin.sums)
        if pin.url not in hashed:
            hashed[pin.url] = _download_sha256(pin.url)
        if hashed[pin.url] != sha:
            raise TrackError(f"{pin.url} hashes to {hashed[pin.url]}, but {pin.sums} says {sha}")
        changes.append(Change(pin, read_pin(tree, pin), sha))
        write_pin(tree, pin, sha)
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
    if _series(old) == _series(new):
        head = f"Patch release of **{component.name}** in the pinned `{_series(new)}` series: `{old}` → `{new}`."
    else:
        head = f"Moves **{component.name}** from `{old}` to `{new}`, a series change."
    lines = [head, "", f"Release notes: {component.notes(new)}", "", "| File | Asset | sha256 |", "| --- | --- | --- |"]
    for pin, before, after in result.changes:
        was = "unchanged" if before == after else f"was `{before}`"
        lines.append(f"| `{pin.path}` | [`{pin.asset}`]({pin.url}) | `{after}` ({was}) |")
    lines += [
        "",
        "Every sha256 comes from the checksum file upstream publishes next to the",
        "asset, and matched the sha256 of the downloaded asset:",
        "",
        *[f"- {url}" for url in dict.fromkeys(change.pin.sums for change in result.changes)],
    ]
    if result.mentions:
        lines += ["", f"These lines of the changed files still mention `{old}`:", ""]
        lines += [f"- `{mention}`" for mention in result.mentions]
    lines += [
        "",
        "Only patch releases inside the pinned series are proposed; a minor bump is a",
        f"manual `.github/scripts/track-binaries.py apply {component.name} --version ...`.",
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
        rows.append({"component": name, "series": _series(current), "current": current, "latest": latest})
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
        print(f"{'component':<12} {'series':<6} {'current':<14} {'latest':<14} state", file=table)
        for row in rows:
            state = "update" if row["latest"] != row["current"] else "current"
            print(f"{row['component']:<12} {row['series']:<6} {row['current']:<14} {row['latest']:<14} {state}", file=table)
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
