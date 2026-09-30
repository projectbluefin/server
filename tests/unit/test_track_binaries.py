"""Behaviour of .github/scripts/track-binaries.py.

No network: urllib.request.urlopen is replaced by a fake upstream serving the
release listings, checksum files and assets each test registers. The fixture
repository mirrors the layout of the real include/, elements/, Justfile and
workflow files; the last tests read the real files, without network, so a
reformat that the tracker cannot follow fails here instead of in the scheduled
run.
"""

import hashlib
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".github" / "scripts" / "track-binaries.py"

_spec = importlib.util.spec_from_file_location("track_binaries", SCRIPT)
assert _spec is not None and _spec.loader is not None
track = importlib.util.module_from_spec(_spec)
sys.modules["track_binaries"] = track
_spec.loader.exec_module(track)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


OLD = {name: sha(name.encode()) for name in ("kubelet", "kubeadm", "kubectl", "crictl", "containerd", "runc", "cni", "k0s", "oras")}

FILES = {
    "include/aliases.yml": "aliases:\n  github: https://github.com/\n  k8s_dl: https://dl.k8s.io/\n",
    "include/kubeadm.yml": """variables:
  # kubelet, kubeadm, kubectl
  kubernetes-version: "1.34.3"
  # crictl
  crictl-version: "1.34.0"
  # containerd
  containerd-version: "2.1.5"
  # runc
  runc-version: "1.3.3"
  # CNI plugins
  cni-plugins-version: "1.1.1"
  # sandbox
  pause-image: "registry.k8s.io/pause:3.10.1"
""",
    "elements/kubeadm/kubeadm-bin.bst": f"""kind: manual

(@):
- include/kubeadm.yml

sources:
- kind: remote
  url: k8s_dl:release/v%{{kubernetes-version}}/bin/linux/amd64/kubelet
  ref: {OLD['kubelet']}
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{{kubernetes-version}}/bin/linux/amd64/kubeadm
  ref: {OLD['kubeadm']}
  directory: k8s
- kind: remote
  url: k8s_dl:release/v%{{kubernetes-version}}/bin/linux/amd64/kubectl
  ref: {OLD['kubectl']}
  directory: k8s
- kind: tar
  url: github:kubernetes-sigs/cri-tools/releases/download/v%{{crictl-version}}/crictl-v%{{crictl-version}}-linux-amd64.tar.gz
  ref: {OLD['crictl']}
  base-dir: ''
- kind: tar
  url: github:containerd/containerd/releases/download/v%{{containerd-version}}/containerd-static-%{{containerd-version}}-linux-amd64.tar.gz
  ref: {OLD['containerd']}
  base-dir: bin
- kind: remote
  url: github:opencontainers/runc/releases/download/v%{{runc-version}}/runc.amd64
  ref: {OLD['runc']}
  directory: runc
- kind: tar
  url: github:containernetworking/plugins/releases/download/v%{{cni-plugins-version}}/cni-plugins-linux-amd64-v%{{cni-plugins-version}}.tgz
  ref: {OLD['cni']}
  base-dir: ''

config:
  install-commands:
  - install -m 0755 runc/runc.amd64 "%{{install-root}}%{{bindir}}/runc"
""",
    "include/k0s.yml": """variables:
  k0s-k8s-version: "1.36.4"
  k0s-patch: "0"

  k0s-upstream-tag: "v%{k0s-k8s-version}%2Bk0s.%{k0s-patch}"
  k0s-version: "%{k0s-k8s-version}-k0s.%{k0s-patch}"
""",
    "elements/k0s/k0s-bin.bst": f"""kind: manual
(@): include/k0s.yml

sources:
  - kind: remote
    url: github:k0sproject/k0s/releases/download/%{{k0s-upstream-tag}}/k0s-%{{k0s-upstream-tag}}-amd64
    ref: {OLD['k0s']}

config:
  install-commands:
    - install -D -m 0755 k0s-%{{k0s-upstream-tag}}-amd64 "%{{install-root}}/usr/bin/k0s"
""",
    "Justfile": 'export oras_image := env("ORAS_IMAGE", "ghcr.io/oras-project/oras:v1.3.4")\n',
    ".github/workflows/build.yml": f"""jobs:
  release:
    steps:
      # pin 1.3.4 (matching the Justfile's oras_image) by URL and checksum.
      - name: Set up oras
        uses: oras-project/setup-oras@1d808f7d7f6995cc68b7bf507bfe5c5446e1dc9d # v2.0.1
        with:
          url: https://github.com/oras-project/oras/releases/download/v1.3.4/oras_1.3.4_linux_amd64.tar.gz
          checksum: {OLD['oras']}

      - name: Push
        run: oras push
  release-dry-run:
    steps:
      - name: Set up oras
        uses: oras-project/setup-oras@1d808f7d7f6995cc68b7bf507bfe5c5446e1dc9d # v2.0.1
        with:
          url: https://github.com/oras-project/oras/releases/download/v1.3.4/oras_1.3.4_linux_amd64.tar.gz
          checksum: {OLD['oras']}
""",
}


class Upstream:
    """Serves registered URLs; everything else is a 404."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.requests: list[urllib.request.Request] = []

    def urlopen(self, request, timeout=None):
        self.requests.append(request)
        if request.full_url not in self.files:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", Message(), None)
        return io.BytesIO(self.files[request.full_url])

    def asset(self, url: str, sums_url: str | None = None, name: str | None = None) -> str:
        data = f"payload of {url}".encode()
        self.files[url] = data
        if sums_url:
            self.files[sums_url] = f"{sha(data)}  {name or url.rsplit('/', 1)[1]}\n".encode()
        return sha(data)

    def releases(self, repo: str, *pages: list[dict]) -> None:
        for number, page in enumerate(pages, 1):
            url = f"https://api.github.com/repos/{repo}/releases?per_page=100&page={number}"
            self.files[url] = json.dumps(page).encode()


def release(tag: str, *assets: str, prerelease: bool = False, draft: bool = False) -> dict:
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "assets": [{"name": a} for a in assets]}


def containerd(version: str) -> dict:
    name = f"containerd-static-{version}-linux-amd64.tar.gz"
    return release(f"v{version}", name, f"{name}.sha256sum")


CONTAINERD = "https://github.com/containerd/containerd/releases/download/v2.1.9/containerd-static-2.1.9-linux-amd64.tar.gz"


@pytest.fixture
def upstream(monkeypatch):
    fake = Upstream()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    return fake


@pytest.fixture
def repo(tmp_path):
    for path, text in FILES.items():
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text, encoding="utf-8")
    return tmp_path


def snapshot(root: Path) -> dict[str, str]:
    return {path: (root / path).read_text(encoding="utf-8") for path in FILES}


def changed_lines(before: dict[str, str], root: Path) -> dict[str, list[tuple[str, str]]]:
    diff = {}
    for path, text in before.items():
        pairs = [(a, b) for a, b in zip(text.splitlines(), (root / path).read_text(encoding="utf-8").splitlines()) if a != b]
        if pairs:
            diff[path] = pairs
    return diff


def newest(name: str, repo: Path) -> str:
    return track.newest(track.COMPONENTS[name], track.Tree(repo))


def test_newest_stays_inside_the_pinned_minor_and_skips_unreleased(repo, upstream):
    upstream.releases("containerd/containerd", [
        containerd("2.2.0"),
        {**containerd("2.1.11"), "prerelease": True},
        containerd("2.1.10-rc.1"),
        {**containerd("2.1.9"), "draft": True},
        containerd("2.1.8"),
        containerd("2.1.5"),
        containerd("1.7.30"),
        release("api/v1.9.0"),
    ])
    assert newest("containerd", repo) == "2.1.8"


def test_release_still_missing_its_assets_is_not_a_candidate(repo, upstream):
    upstream.releases("containerd/containerd", [
        release("v2.1.9", "containerd-static-2.1.9-linux-amd64.tar.gz"),
        containerd("2.1.8"),
    ])
    assert newest("containerd", repo) == "2.1.8"


def test_release_listing_is_paginated(repo, upstream):
    upstream.releases("containerd/containerd", [containerd(f"1.7.{n}") for n in range(100)], [containerd("2.1.9")])
    assert newest("containerd", repo) == "2.1.9"


def test_kubernetes_follows_the_dl_k8s_io_stable_channel(repo, upstream):
    upstream.files["https://dl.k8s.io/release/stable-1.34.txt"] = b"v1.34.12\n"
    assert newest("kubernetes", repo) == "1.34.12"
    upstream.files["https://dl.k8s.io/release/stable-1.34.txt"] = b"v1.35.0\n"
    with pytest.raises(track.TrackError, match="not a 1.34.x release"):
        newest("kubernetes", repo)


def test_k0s_orders_by_kubernetes_patch_then_k0s_suffix(repo, upstream):
    def k0s(tag: str) -> dict:
        return release(tag, f"k0s-{tag}-amd64", "sha256sums.txt")

    upstream.releases("k0sproject/k0s", [k0s("v1.37.0+k0s.0"), k0s("v1.36.4+k0s.1"), k0s("v1.36.3+k0s.2"), k0s("v1.36.4+k0s.0")])
    assert newest("k0s", repo) == "1.36.4+k0s.1"
    upstream.releases("k0sproject/k0s", [k0s("v1.36.5+k0s.0"), k0s("v1.36.4+k0s.1")])
    assert newest("k0s", repo) == "1.36.5+k0s.0"


def test_check_json_lists_pending_updates_and_still_reports_errors(repo, upstream, monkeypatch, capsys):
    monkeypatch.setattr(track, "COMPONENTS", {n: track.COMPONENTS[n] for n in ("containerd", "runc", "cni-plugins")})
    upstream.releases("containerd/containerd", [containerd("2.1.9"), containerd("2.1.5")])
    upstream.releases("opencontainers/runc", [release("v1.3.3", "runc.amd64", "runc.sha256sum")])
    assert track.main(["check", "--json"], root=repo) == 1
    out, err = capsys.readouterr()
    assert json.loads(out) == [{"component": "containerd", "series": "2.1", "current": "2.1.5", "latest": "2.1.9"}]
    assert "runc         1.3    1.3.3          1.3.3          current" in err
    assert "ERROR: cni-plugins: GET https://api.github.com/repos/containernetworking/plugins/releases" in err


def test_apply_moves_the_version_and_only_its_own_ref(repo, upstream, tmp_path, capsys):
    upstream.releases("containerd/containerd", [containerd("2.1.9"), containerd("2.1.5")])
    new = upstream.asset(CONTAINERD, CONTAINERD + ".sha256sum")
    before = snapshot(repo)
    body = tmp_path / "body.md"

    assert track.main(["apply", "containerd", "--summary", str(body)], root=repo) == 0

    assert changed_lines(before, repo) == {
        "include/kubeadm.yml": [('  containerd-version: "2.1.5"', '  containerd-version: "2.1.9"')],
        "elements/kubeadm/kubeadm-bin.bst": [(f"  ref: {OLD['containerd']}", f"  ref: {new}")],
    }
    assert capsys.readouterr().out.split() == ["elements/kubeadm/kubeadm-bin.bst", "include/kubeadm.yml"]
    text = body.read_text()
    assert "Patch release of **containerd** in the pinned `2.1` series: `2.1.5` → `2.1.9`." in text
    assert f"`{new}` (was `{OLD['containerd']}`)" in text
    assert f"- {CONTAINERD}.sha256sum" in text
    assert "https://github.com/containerd/containerd/releases/tag/v2.1.9" in text


def test_apply_kubernetes_rewrites_all_three_binaries_from_bare_digests(repo, upstream):
    upstream.files["https://dl.k8s.io/release/stable-1.34.txt"] = b"v1.34.12"
    new = {}
    for binary in ("kubelet", "kubeadm", "kubectl"):
        url = f"https://dl.k8s.io/release/v1.34.12/bin/linux/amd64/{binary}"
        upstream.files[url] = binary.encode() * 3
        upstream.files[url + ".sha256"] = sha(binary.encode() * 3).encode()
        new[binary] = sha(binary.encode() * 3)
    before = snapshot(repo)

    assert track.main(["apply", "kubernetes"], root=repo) == 0

    assert changed_lines(before, repo) == {
        "include/kubeadm.yml": [('  kubernetes-version: "1.34.3"', '  kubernetes-version: "1.34.12"')],
        "elements/kubeadm/kubeadm-bin.bst": [(f"  ref: {OLD[b]}", f"  ref: {new[b]}") for b in ("kubelet", "kubeadm", "kubectl")],
    }


def test_apply_runc_reads_its_pgp_signed_sums_file(repo, upstream):
    url = "https://github.com/opencontainers/runc/releases/download/v1.3.6/runc.amd64"
    new = upstream.asset(url)
    upstream.files[url.rsplit("/", 1)[0] + "/runc.sha256sum"] = (
        "-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA512\n\n"
        f"{sha(b'arm64')}  runc.arm64\n{new}  runc.amd64\n{sha(b'tar')}  runc.tar.xz\n"
        "-----BEGIN PGP SIGNATURE-----\n\niQIzBAEBCgAdFiEE\n-----END PGP SIGNATURE-----\n"
    ).encode()

    assert track.main(["apply", "runc", "--version", "1.3.6"], root=repo) == 0

    assert f"ref: {new}" in (repo / "elements/kubeadm/kubeadm-bin.bst").read_text()


def test_apply_k0s_moves_both_atoms_and_downloads_the_escaped_tag(repo, upstream):
    url = "https://github.com/k0sproject/k0s/releases/download/v1.36.4%2Bk0s.1/k0s-v1.36.4%2Bk0s.1-amd64"
    new = upstream.asset(url)
    upstream.files[url.rsplit("/", 1)[0] + "/sha256sums.txt"] = (
        f"{sha(b'airgap')} *k0s-airgap-bundle-v1.36.4+k0s.1-linux-amd64.tar\n{new} *k0s-v1.36.4+k0s.1-amd64\n"
    ).encode()
    before = snapshot(repo)

    assert track.main(["apply", "k0s", "--version", "1.36.4+k0s.1"], root=repo) == 0

    assert changed_lines(before, repo) == {
        "include/k0s.yml": [('  k0s-patch: "0"', '  k0s-patch: "1"')],
        "elements/k0s/k0s-bin.bst": [(f"    ref: {OLD['k0s']}", f"    ref: {new}")],
    }
    assert url in [r.full_url for r in upstream.requests]


def test_apply_oras_moves_the_justfile_tag_and_every_setup_oras_pin(repo, upstream, tmp_path):
    url = "https://github.com/oras-project/oras/releases/download/v1.3.5/oras_1.3.5_linux_amd64.tar.gz"
    new = upstream.asset(url, url.rsplit("/", 1)[0] + "/oras_1.3.5_checksums.txt")
    body = tmp_path / "body.md"

    assert track.main(["apply", "oras", "--version", "1.3.5", "--summary", str(body)], root=repo) == 0

    assert "ghcr.io/oras-project/oras:v1.3.5" in (repo / "Justfile").read_text()
    workflow = (repo / ".github/workflows/build.yml").read_text()
    assert workflow.count(f"url: {url}") == 2
    assert workflow.count(f"checksum: {new}") == 2
    assert "1.3.4" in workflow.split("\n")[3]
    assert "`.github/workflows/build.yml:4: # pin 1.3.4 (matching the Justfile's oras_image) by URL and checksum.`" in body.read_text()


def test_oras_pins_that_disagree_are_refused(repo, upstream):
    (repo / "Justfile").write_text('export oras_image := env("ORAS_IMAGE", "ghcr.io/oras-project/oras:v1.3.3")\n')
    with pytest.raises(track.TrackError, match=r"ORAS pins disagree \(\.github/workflows/build\.yml: 1\.3\.4, Justfile: 1\.3\.3\)"):
        track.apply(repo, "oras", "1.3.5")


def test_asset_that_does_not_match_its_published_checksum_writes_nothing(repo, upstream, capsys):
    upstream.releases("containerd/containerd", [containerd("2.1.9")])
    upstream.asset(CONTAINERD, CONTAINERD + ".sha256sum")
    upstream.files[CONTAINERD] = b"tampered"
    before = snapshot(repo)

    assert track.main(["apply", "containerd"], root=repo) == 1

    assert snapshot(repo) == before
    assert f"{CONTAINERD} hashes to {sha(b'tampered')}" in capsys.readouterr().err


def test_checksum_file_that_omits_the_asset_is_refused(repo, upstream):
    upstream.asset(CONTAINERD)
    upstream.files[CONTAINERD + ".sha256sum"] = f"{sha(b'x')}  containerd-2.1.9-linux-amd64.tar.gz\n".encode()
    with pytest.raises(track.TrackError, match="lists 0 sha256 for containerd-static-2.1.9-linux-amd64.tar.gz"):
        track.apply(repo, "containerd", "2.1.9")


def test_apply_is_a_no_op_when_the_pin_is_already_newest(repo, upstream, capsys):
    upstream.releases("containerd/containerd", [containerd("2.1.5"), containerd("2.1.4")])
    before = snapshot(repo)
    assert track.main(["apply", "containerd"], root=repo) == 0
    assert snapshot(repo) == before
    assert capsys.readouterr().out == ""


def test_manual_minor_bump_uses_the_same_verification(repo, upstream, tmp_path):
    for binary in ("kubelet", "kubeadm", "kubectl"):
        url = f"https://dl.k8s.io/release/v1.35.2/bin/linux/amd64/{binary}"
        upstream.files[url] = binary.encode()
        upstream.files[url + ".sha256"] = sha(binary.encode()).encode()
    body = tmp_path / "body.md"

    assert track.main(["apply", "kubernetes", "--version", "1.35.2", "--summary", str(body)], root=repo) == 0

    assert 'kubernetes-version: "1.35.2"' in (repo / "include/kubeadm.yml").read_text()
    assert "a series change" in body.read_text()
    assert not any("stable-" in r.full_url for r in upstream.requests)


def test_malformed_version_is_refused_before_any_download(repo, upstream):
    with pytest.raises(track.TrackError, match="does not match"):
        track.apply(repo, "k0s", "1.36.5")
    assert upstream.requests == []


def test_source_without_its_own_ref_does_not_borrow_the_next_one(repo, upstream):
    bst = repo / "elements/kubeadm/kubeadm-bin.bst"
    bst.write_text(bst.read_text().replace(f"  ref: {OLD['containerd']}\n", ""))
    upstream.asset(CONTAINERD, CONTAINERD + ".sha256sum")
    with pytest.raises(track.TrackError, match="no `ref:` in the mapping of `url: github:containerd/"):
        track.apply(repo, "containerd", "2.1.9")
    assert f"ref: {OLD['runc']}" in bst.read_text()


def test_github_token_is_sent_to_the_api_and_never_to_downloads(repo, upstream, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    upstream.releases("containerd/containerd", [containerd("2.1.9")])
    upstream.asset(CONTAINERD, CONTAINERD + ".sha256sum")

    track.apply(repo, "containerd")

    auth = {r.full_url.split("?")[0]: r.get_header("Authorization") for r in upstream.requests}
    assert auth == {
        "https://api.github.com/repos/containerd/containerd/releases": "Bearer secret-token",
        CONTAINERD + ".sha256sum": None,
        CONTAINERD: None,
    }


ARM64_OLD = {name: sha(f"{name} arm64".encode()) for name in ("runc", "k0s")}


def add_arm64(repo: Path) -> None:
    """Give the fixture the real layout's `(?): arch == "aarch64"` sources."""
    bst = repo / "elements/kubeadm/kubeadm-bin.bst"
    bst.write_text(bst.read_text().replace("\nconfig:", f"""
(?):
- arch == "aarch64":
    sources:
    - kind: remote
      url: github:opencontainers/runc/releases/download/v%{{runc-version}}/runc.arm64
      ref: {ARM64_OLD['runc']}
      directory: runc

config:""", 1))
    k0s = repo / "elements/k0s/k0s-bin.bst"
    k0s.write_text(k0s.read_text().replace("\nconfig:", f"""
(?):
  - arch == "aarch64":
      sources:
        - kind: remote
          url: github:k0sproject/k0s/releases/download/%{{k0s-upstream-tag}}/k0s-%{{k0s-upstream-tag}}-arm64
          ref: {ARM64_OLD['k0s']}

config:""", 1))


RUNC = "https://github.com/opencontainers/runc/releases/download/v1.3.6/"


def runc_release(upstream: Upstream, *arches: str) -> dict[str, str]:
    new = {}
    for arch in arches:
        upstream.files[RUNC + f"runc.{arch}"] = f"runc {arch} 1.3.6".encode()
        new[arch] = sha(f"runc {arch} 1.3.6".encode())
    upstream.files[RUNC + "runc.sha256sum"] = "".join(f"{d}  runc.{a}\n" for a, d in new.items()).encode()
    upstream.releases("opencontainers/runc", [
        release("v1.3.6", *(f"runc.{a}" for a in arches), "runc.sha256sum"),
        release("v1.3.3", "runc.amd64", "runc.arm64", "runc.sha256sum"),
    ])
    return new


def test_bump_refreshes_every_architecture_together(repo, upstream):
    add_arm64(repo)
    new = runc_release(upstream, "amd64", "arm64")
    before = snapshot(repo)

    assert track.main(["apply", "runc"], root=repo) == 0

    assert changed_lines(before, repo) == {
        "include/kubeadm.yml": [('  runc-version: "1.3.3"', '  runc-version: "1.3.6"')],
        "elements/kubeadm/kubeadm-bin.bst": [
            (f"  ref: {OLD['runc']}", f"  ref: {new['amd64']}"),
            (f"      ref: {ARM64_OLD['runc']}", f"      ref: {new['arm64']}"),
        ],
    }
    fetched = [r.full_url for r in upstream.requests]
    assert RUNC + "runc.amd64" in fetched and RUNC + "runc.arm64" in fetched


def test_k0s_bump_refreshes_the_arm64_binary_too(repo, upstream):
    add_arm64(repo)
    base = "https://github.com/k0sproject/k0s/releases/download/v1.36.4%2Bk0s.1/"
    new = {a: upstream.asset(base + f"k0s-v1.36.4%2Bk0s.1-{a}") for a in ("amd64", "arm64")}
    upstream.files[base + "sha256sums.txt"] = "".join(
        f"{d} *k0s-v1.36.4+k0s.1-{a}\n" for a, d in new.items()).encode()
    before = snapshot(repo)

    assert track.main(["apply", "k0s", "--version", "1.36.4+k0s.1"], root=repo) == 0

    assert changed_lines(before, repo)["elements/k0s/k0s-bin.bst"] == [
        (f"    ref: {OLD['k0s']}", f"    ref: {new['amd64']}"),
        (f"          ref: {ARM64_OLD['k0s']}", f"          ref: {new['arm64']}"),
    ]


def test_release_without_its_arm64_asset_is_not_proposed(repo, upstream):
    add_arm64(repo)
    runc_release(upstream, "amd64")
    assert newest("runc", repo) == "1.3.3"


def test_missing_arm64_checksum_fails_the_component_and_writes_nothing(repo, upstream, capsys):
    add_arm64(repo)
    runc_release(upstream, "amd64")
    upstream.asset(RUNC + "runc.arm64")  # asset exists, but the sums file omits it
    before = snapshot(repo)

    assert track.main(["apply", "runc", "--version", "1.3.6"], root=repo) == 1

    assert snapshot(repo) == before
    assert "lists 0 sha256 for runc.arm64" in capsys.readouterr().err


def test_missing_arm64_asset_fails_the_component_and_writes_nothing(repo, upstream, capsys):
    add_arm64(repo)
    new = runc_release(upstream, "amd64", "arm64")
    del upstream.files[RUNC + "runc.arm64"]
    before = snapshot(repo)

    assert track.main(["apply", "runc", "--version", "1.3.6"], root=repo) == 1

    assert snapshot(repo) == before
    assert new["arm64"] not in (repo / "elements/kubeadm/kubeadm-bin.bst").read_text()
    assert f"GET {RUNC}runc.arm64: HTTP 404" in capsys.readouterr().err


def test_no_op_run_leaves_multi_arch_files_byte_identical(repo, upstream, capsys):
    add_arm64(repo)
    upstream.releases("opencontainers/runc", [release("v1.3.3", "runc.amd64", "runc.arm64", "runc.sha256sum")])
    before = {p: (repo / p).read_bytes() for p in FILES}

    assert track.main(["apply", "runc"], root=repo) == 0

    assert {p: (repo / p).read_bytes() for p in FILES} == before
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("name", [n for n, c in track.COMPONENTS.items() if isinstance(c, track.BstComponent)])
def test_real_elements_pin_amd64_and_arm64_alike(name):
    pins = track.COMPONENTS[name].pins(track.Tree(ROOT))
    by_arch = {arch: sorted(p.url.replace(arch, "ARCH") for p in pins if arch in p.url) for arch in ("amd64", "arm64")}
    assert by_arch["amd64"] and by_arch["amd64"] == by_arch["arm64"]
    assert len(pins) == len(by_arch["amd64"]) * 2


@pytest.mark.parametrize("name", list(track.COMPONENTS))
def test_real_pins_are_readable(name):
    tree = track.Tree(ROOT)
    component = track.COMPONENTS[name]
    component.parse(component.current(tree))
    pins = component.pins(tree)
    assert pins
    for pin in pins:
        assert pin.url.startswith("https://") and "%{" not in pin.url
        assert track.SUMS_LINE_RE.match(track.read_pin(tree, pin)), pin


def test_every_pinned_source_belongs_to_exactly_one_component():
    tree = track.Tree(ROOT)
    elements = {c.element for c in track.COMPONENTS.values() if isinstance(c, track.BstComponent)}
    for element in sorted(elements):
        for line in tree[element].splitlines():
            match = track.URL_LINE_RE.match(line)
            if match:
                owners = [c.name for c in track.COMPONENTS.values() if getattr(c, "marker", None) and c.marker in match["url"]]
                assert len(owners) == 1, f"{element}: {match['url']} is tracked by {owners}"
