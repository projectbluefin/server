#!/usr/bin/env python3
"""Measure an exported image set (dist/diskless/) against the latest release.

Prints a JSON size report to stdout and its Markdown table to
$GITHUB_STEP_SUMMARY (stderr when unset). Every metric is a size in bytes:

* os_ddi_raw, usr_raw, usr_verity_raw, disk_uki, netboot_uki,
  netboot_esp_raw, installer_raw: the release files of those kinds;
* <name>_sysext_raw_zst: each *.raw.zst (the homebrew machine image too);
* uki_linux_section, uki_initrd_section: the disk UKI's PE sections, and
  initrd_unpacked: the size of the files in that initrd.

A file the set lacks, or a disk UKI that is not a PE file, has no metric.
With --baseline-json (the latest release's report) or --baseline-usr (its
*.usr.raw, usr_raw only, for a release without a report) the report holds
each metric's change too; growth by more than 5 % or 5 MiB gets a ::warning::
annotation, never a failure. Releases publish the report next to the set,
outside its signed SHA256SUMS: it is information, nothing trusts it.

--render prints the table of a report, for publish-release.sh's release
notes. Needs zstd on PATH for initrd_unpacked.
"""


import argparse
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

# The image version in a release file name (publish-release.sh,
# expected_patterns).
V = r"(?P<v>[0-9][^_]*)"
# Metric -> release file, in table order.
FILES = {
    "os_ddi_raw": rf"bluefin-server_{V}\.raw",
    "usr_raw": rf"bluefin-server_{V}_[0-9a-f-]+\.usr\.raw",
    "usr_verity_raw": rf"bluefin-server_{V}_[0-9a-f-]+\.usr-verity\.raw",
    "disk_uki": rf"bluefin-server-{V}\.efi",
    "netboot_uki": rf"bluefin-server-netboot_{V}\.efi",
    "netboot_esp_raw": rf"bluefin-server-netboot_{V}\.esp\.raw",
    "installer_raw": rf"bluefin-server-installer_{V}\.raw",
}
SECTIONS = {"uki_linux_section": ".linux", "uki_initrd_section": ".initrd"}
ORDER = [*FILES, *SECTIONS, "initrd_unpacked"]
# <name>_<image version>.raw.zst, or <name>-<own version>.raw.zst (k0s, the
# NVIDIA Container Toolkit).
SYSEXT = re.compile(r"(?P<name>.+?)[_-][0-9][^_]*\.raw\.zst")
NOT_NUL = re.compile(rb"[^\x00]")
GROWTH_RATIO = 0.05
GROWTH_BYTES = 5 * 2**20


def pe_sections(data: bytes) -> dict[str, tuple[int, int]]:
    """Name -> (file offset, size) of each section of a PE file; {} for anything else."""
    try:
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[:2] != b"MZ" or data[pe : pe + 4] != b"PE\x00\x00":
            return {}
        count = struct.unpack_from("<H", data, pe + 6)[0]
        optional = struct.unpack_from("<H", data, pe + 20)[0]
        sections = {}
        for i in range(count):
            entry = pe + 24 + optional + 40 * i
            size, _, _, offset = struct.unpack_from("<IIII", data, entry + 8)
            sections[data[entry : entry + 8].rstrip(b"\x00").decode()] = (offset, size)
        return sections
    except (struct.error, UnicodeDecodeError):
        return {}


def cpio_size(data: bytes) -> int:
    """Total size of the files in a newc cpio stream of one or more archives."""
    total, pos = 0, 0
    while (start := NOT_NUL.search(data, pos)) is not None:
        pos = start.start()
        if data[pos : pos + 6] not in (b"070701", b"070702"):
            raise ValueError(f"no newc cpio header at offset {pos}")
        size, namesize = int(data[pos + 54 : pos + 62], 16), int(data[pos + 94 : pos + 102], 16)
        name = data[pos + 110 : pos + 109 + namesize]
        pos = (pos + 110 + namesize + 3) & ~3
        if name != b"TRAILER!!!":
            total += size
        pos = (pos + size + 3) & ~3
    return total


def measure(dist: Path) -> tuple[dict[str, int], str | None]:
    """The metrics of the image set in dist, and its image version."""
    names = sorted(p.name for p in dist.iterdir() if p.is_file())
    paths: dict[str, Path] = {}
    versions: set[str] = set()
    for metric, pattern in FILES.items():
        found = [m for m in map(re.compile(pattern).fullmatch, names) if m]
        if len(found) > 1:
            raise SystemExit(f"{metric}: more than one file in {dist}: {[m.string for m in found]}")
        if found:
            paths[metric] = dist / found[0].string
            versions.add(found[0]["v"])
    metrics = {metric: path.stat().st_size for metric, path in paths.items()}
    if len(versions) > 1:
        raise SystemExit(f"{dist} holds files of more than one image version: {sorted(versions)}")
    for name in names:
        if match := SYSEXT.fullmatch(name):
            key = match["name"].replace("-", "_") + "_sysext_raw_zst"
            if key in metrics:
                raise SystemExit(f"more than one {match['name']} sysext in {dist}")
            metrics[key] = (dist / name).stat().st_size
    if "disk_uki" in paths:
        data = paths["disk_uki"].read_bytes()
        sections = pe_sections(data)
        for metric, section in SECTIONS.items():
            if section in sections:
                metrics[metric] = sections[section][1]
        if ".initrd" in sections:
            offset, size = sections[".initrd"]
            cpio = subprocess.run(
                ["zstd", "-dcq"], input=data[offset : offset + size], capture_output=True, check=True
            ).stdout
            metrics["initrd_unpacked"] = cpio_size(cpio)
    return metrics, versions.pop() if versions else None


def baseline(report: Path | None, usr: Path | None) -> tuple[str | None, dict[str, int]]:
    """The baseline's version and metrics: usr_raw from a *.usr.raw, all of a report's."""
    version: str | None = None
    metrics: dict[str, int] = {}
    if usr is not None:
        match = re.fullmatch(FILES["usr_raw"], usr.name)
        version = match["v"] if match else usr.name
        metrics["usr_raw"] = usr.stat().st_size
    if report is not None:
        doc = json.loads(report.read_text(encoding="utf-8"))
        version = doc.get("image_version") or version
        metrics.update({k: v for k, v in doc.get("metrics", {}).items() if isinstance(v, int)})
    return version, metrics


def human(n: int) -> str:
    for unit, scale in (("GiB", 2**30), ("MiB", 2**20), ("KiB", 2**10)):
        if abs(n) >= scale:
            return f"{n / scale:.1f} {unit}"
    return f"{n} B"


def grew(value: int, delta: int) -> bool:
    """Grew by more than GROWTH_BYTES, or by more than GROWTH_RATIO of the baseline."""
    return delta > GROWTH_BYTES or delta > GROWTH_RATIO * (value - delta)


def change(value: int, delta: int) -> str:
    text = ("+" if delta > 0 else "") + human(delta)
    base = value - delta
    return f"{text} ({delta / base:+.1%})" if base else text


def render(report: dict[str, Any]) -> str:
    """The Markdown table of a size report; changes in bold grew too much."""
    metrics: dict[str, int] = report["metrics"]
    delta: dict[str, int] = report.get("delta") or {}
    since = report.get("baseline")
    head, rule = "| File or section | Size |", "| --- | ---: |"
    if since:
        head, rule = f"{head} Change since {since} |", f"{rule} ---: |"
    lines = [head, rule]
    for key in [k for k in ORDER if k in metrics] + sorted(set(metrics) - set(ORDER)):
        row = f"| `{key}` | {human(metrics[key])} |"
        if since:
            cell = change(metrics[key], delta[key]) if key in delta else ""
            if key in delta and grew(metrics[key], delta[key]):
                cell = f"**{cell}**"
            row += f" {cell} |"
        lines.append(row)
    if any(grew(metrics[k], d) for k, d in delta.items() if k in metrics):
        lines += ["", f"Bold: grew by more than {GROWTH_RATIO:.0%} or {human(GROWTH_BYTES)}."]
    return "\n".join(lines) + "\n"


def git_head() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("dist", type=Path, nargs="?", help="exported image set, e.g. dist/diskless")
    what.add_argument("--render", type=Path, metavar="REPORT", help="print the table of a size report")
    parser.add_argument("--baseline-json", type=Path, help="the latest release's size report")
    parser.add_argument("--baseline-usr", type=Path, help="the latest release's *.usr.raw")
    parser.add_argument("--commit", help="the commit the set was built from (default: git HEAD)")
    args = parser.parse_args(argv)
    if args.render is not None:
        sys.stdout.write(render(json.loads(args.render.read_text(encoding="utf-8"))))
        return 0

    metrics, version = measure(args.dist)
    since, base = baseline(args.baseline_json, args.baseline_usr)
    delta = {k: v - base[k] for k, v in metrics.items() if k in base}
    report = {
        "baseline": since,
        "commit": args.commit or git_head(),
        "delta": delta,
        "image_version": version,
        "metrics": metrics,
    }
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    for key, value in sorted(delta.items()):
        if grew(metrics[key], value):
            print(
                f"::warning title=Image size grew::{key} grew by {change(metrics[key], value)}"
                f" since {since}, to {human(metrics[key])}",
                file=sys.stderr,
            )
    summary = f"### Image sizes{f' of {version}' if version else ''}\n\n{render(report)}"
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    else:
        sys.stderr.write(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
