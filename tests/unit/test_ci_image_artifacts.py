"""build.yml uploads the image sets in parts, by what their consumers read.

- Each image set's parts are rooted at the set's directory, so merging them
  rebuilds it as built, and its catch-all part excludes exactly what the
  other parts include: every file, also one the set does not have yet, lands
  in exactly one part.
- image-check, release and release-dry-run download every image-set part into
  dist/diskless, so the release publishes the full set.
- A boot-test bucket downloads the parts its dogfood scripts read, and every
  part a later consumer reads is uploaded with if-no-files-found: error.
"""


import fnmatch
import itertools
import os
import re
import subprocess
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
JOBS = yaml.safe_load((ROOT / ".github" / "workflows" / "build.yml").read_text(encoding="utf-8"))["jobs"]
BUILD = JOBS["build"]
BOOT_TEST = JOBS["boot-test"]
INCLUDE = {entry["scenario"]: entry for entry in BOOT_TEST["strategy"]["matrix"]["include"]}

UPLOADS = {s["with"]["name"]: s for s in BUILD["steps"] if s.get("uses", "").startswith("actions/upload-artifact@")}
SETS = {"image-set": ("dist/diskless", "image-set-core"), "image-next": ("dist/diskless-next", "image-next-boot")}

V = "0.42"
# The set as oci/bluefin-server-image.bst lays it out, and names it does not have yet.
SET_FILES = {
    f"bluefin-server_{V}.raw": "netboot",
    f"bluefin-server-netboot_{V}.efi": "netboot",
    f"bluefin-server-netboot_{V}.esp.raw": "netboot",
    f"bluefin-server-installer_{V}.raw": "installer",
    f"bluefin-server_{V}_f7ec003a-f0a4-930d-c165-f0e8d9eef3ff.usr.raw": "sysupdate",
    f"bluefin-server_{V}_ad0e16ea-f571-bf1b-a2a1-205ded9b1e16.usr-verity.raw": "sysupdate",
    f"bluefin-server-{V}.efi": "sysupdate",
    f"zfs_{V}.raw.zst": "sysexts",
    "k0s-1.36.4-k0s.1.raw.zst": "sysexts",
    "nvidia-container-toolkit-1.20.1.raw.zst": "sysexts",
    "SHA256SUMS": "core",
    "SHA256SUMS.gpg": "core",
    f"bluefin-server_{V}.spdx.json": "core",
    "homelab-node.bu": "core",
    "homelab-node.ign": "core",
    "home-server.bu": "core",
    "efi-keys/PK.auth": "core",
    "sysupdate-keys/import-pubring.pgp": "core",
    "a-new-asset.bin": "core",
    "newdir/nested.raw.zst": "core",
    f"bluefin-server-{V}.efi.sig": "core",
}


def paths(step: dict) -> list[str]:
    return [line.strip() for line in step["with"]["path"].splitlines() if line.strip()]


def includes(step: dict) -> list[str]:
    return [p for p in paths(step) if not p.startswith("!")]


def excludes(step: dict) -> list[str]:
    return [p[1:] for p in paths(step) if p.startswith("!")]


def matches(path: str, pattern: str) -> bool:
    # @actions/glob: a directory matches everything below it; * stays within one path segment.
    if pattern.endswith("/"):
        return path.startswith(pattern)
    return PurePosixPath(path).full_match(pattern)


def in_part(path: str, step: dict) -> bool:
    return any(matches(path, p) for p in includes(step)) and not any(matches(path, p) for p in excludes(step))


def search_root(pattern: str) -> str:
    # The artifact root upload-artifact derives from an include path: a
    # directory itself, else the directories before the first wildcard.
    parts = PurePosixPath(pattern).parts
    plain = list(itertools.takewhile(lambda p: not re.search(r"[*?\[]", p), parts))
    if not pattern.endswith("/") and len(plain) == len(parts):
        plain.pop()
    return "/".join(plain)


def selected(pattern: str, names: list[str]) -> set[str]:
    # download-artifact's minimatch pattern; build.yml uses at most one {a,b} group.
    m = re.fullmatch(r"(.*)\{([^}]*)\}(.*)", pattern)
    alternatives = [m[1] + alt + m[3] for alt in m[2].split(",")] if m else [pattern]
    return {n for n in names if any(fnmatch.fnmatchcase(n, a) for a in alternatives)}


def parts_of(prefix: str) -> dict[str, dict]:
    return {name: step for name, step in UPLOADS.items() if name.startswith(prefix + "-")}


@pytest.mark.parametrize("prefix", sorted(SETS))
def test_each_set_is_split_by_a_catch_all_part(prefix: str) -> None:
    directory, catch_all = SETS[prefix]
    parts = parts_of(prefix)
    assert catch_all in parts and len(parts) >= 2
    others = [p for name, step in parts.items() if name != catch_all for p in includes(step)]
    assert includes(parts[catch_all]) == [directory + "/"]
    # Installers are left out of the update sets on purpose; every other exclusion is another part.
    assert set(excludes(parts[catch_all])) - set(others) <= {f"{directory}/bluefin-server-installer_*.raw"}
    assert set(others) <= set(excludes(parts[catch_all]))
    for name, step in parts.items():
        assert {search_root(p) for p in includes(step)} == {directory}, name
        if name != catch_all:
            # What a part leaves out, another part takes.
            assert set(excludes(step)) <= set(others), name


def test_every_file_of_the_image_set_lands_in_exactly_one_part() -> None:
    parts = parts_of("image-set")
    assert set(parts) == {f"image-set-{p}" for p in set(SET_FILES.values())}
    for name, part in SET_FILES.items():
        holders = [n for n, step in parts.items() if in_part(f"dist/diskless/{name}", step)]
        assert holders == [f"image-set-{part}"], name


def test_every_file_of_the_next_set_but_its_installer_lands_in_exactly_one_part() -> None:
    parts = parts_of("image-next")
    for name, part in SET_FILES.items():
        holders = [n for n, step in parts.items() if in_part(f"dist/diskless-next/{name}", step)]
        if part == "installer":
            assert holders == [], name
        else:
            assert holders == ["image-next-update" if part in {"sysupdate", "sysexts"} else "image-next-boot"], name


def test_uploads_fail_on_a_missing_part_and_keep_one_day() -> None:
    for name, step in UPLOADS.items():
        assert step["with"]["if-no-files-found"] == "error", name
        assert step["with"]["retention-days"] == 1, name


@pytest.mark.parametrize("job", ["image-check", "release", "release-dry-run"])
def test_full_set_consumers_download_every_image_set_part(job: str) -> None:
    downloads = [s for s in JOBS[job]["steps"] if s.get("name") == "Download image artifacts"]
    assert len(downloads) == 1
    step = downloads[0]
    assert step["with"] == {"pattern": "image-set-*", "merge-multiple": True, "path": "dist/diskless"}
    every = [*UPLOADS, "image-size", *(f"boot-test-logs-{b}" for b in INCLUDE)]
    assert selected(step["with"]["pattern"], every) == set(parts_of("image-set"))


# The part of the set a dogfood script boots or installs (its first argument)
# that it reads besides the catch-all; a later set argument is an update
# source, read whole.
BOOTS = {
    "scripts/dogfood-diskless.sh": "netboot",
    "scripts/dogfood-install.sh": "netboot",
    "scripts/dogfood-installer.sh": "installer",
}


def set_args(bucket: str) -> list[tuple[str, list[str]]]:
    calls = []
    for release in (False, True):
        out = subprocess.run(
            ["bash", str(ROOT / "scripts" / "ci" / "boot-test.sh"), "--list", bucket],
            cwd=ROOT, env={**os.environ, "RELEASE": "true" if release else "false"},
            capture_output=True, text=True, check=True,
        )
        for line in out.stdout.splitlines():
            words = line.split(": ", 1)[1].split()
            script = next(w for w in words if w.startswith("scripts/dogfood-"))
            calls.append((script, [w for w in words if w.startswith("dist/diskless")]))
    return calls


@pytest.mark.parametrize("bucket", sorted(INCLUDE))
def test_a_bucket_downloads_the_parts_its_scripts_read(bucket: str) -> None:
    downloads = {s["with"]["path"]: s for s in BOOT_TEST["steps"] if s.get("uses", "").startswith("actions/download-artifact@")}
    assert "if" not in downloads["dist/diskless"]
    for path, key in (("dist/diskless", "image"), ("dist/diskless-next", "next")):
        assert downloads[path]["with"] == {"pattern": f"${{{{ matrix.{key} }}}}", "merge-multiple": True, "path": path}

    every = {"core", "netboot", "installer", "sysupdate", "sysexts"}
    need: dict[str, set[str]] = {"dist/diskless": set(), "dist/diskless-next": set(), "dist/diskless-broken": set()}
    for script, sets in set_args(bucket):
        need[sets[0]] |= {"core", BOOTS[script]}
        for later in sets[1:]:
            need[later] |= every
    assert selected(INCLUDE[bucket]["image"], list(UPLOADS)) == {f"image-set-{p}" for p in need["dist/diskless"]}
    got_next = selected(INCLUDE[bucket]["next"], list(UPLOADS)) if INCLUDE[bucket]["next"] else set()
    if not need["dist/diskless-next"]:
        assert got_next == set()
    elif need["dist/diskless-next"] <= {"core", "netboot"}:
        assert got_next == {"image-next-boot"}
    else:
        assert got_next == set(parts_of("image-next"))
