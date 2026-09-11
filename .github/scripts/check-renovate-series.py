#!/usr/bin/env python3
"""Keep Renovate's version filters on the same release series as the junctions.

`elements/*.bst` pin a junction with a `track:` glob and a resolved `ref:`:

    track: freedesktop-sdk-26.08*
    ref: freedesktop-sdk-26.08.0-0-gdb97cce...

`renovate.json` decides which upstream tags are candidates for a bump with a
per-package `extractVersion` anchored to that same series:

    "extractVersion": "^freedesktop-sdk-(?<version>26\\.08\\.[0-9]+)$"

Nothing ties the two together. When a junction moves to a new series and the
Renovate rule does not, the rule stops matching every tag upstream publishes.
Renovate then reports no updates rather than an error, so the junction quietly
stops receiving bumps and the `track-refs` job in build.yml has nothing to
resolve. That is not hypothetical: the freedesktop-sdk rule still read
`25\\.08\\.` after the junction moved to `freedesktop-sdk-26.08.0`.

This script fails closed on that drift. It reads the series out of each
junction's `track:` glob and asserts the matching `extractVersion` in
renovate.json is anchored to the same one.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RENOVATE_JSON = ROOT / "renovate.json"

# depName in renovate.json -> the junction whose `track:` is authoritative.
JUNCTIONS = {
    "https://gitlab.com/freedesktop-sdk/freedesktop-sdk.git": (
        ROOT / "elements" / "freedesktop-sdk.bst"
    ),
    "https://gitlab.gnome.org/GNOME/gnome-build-meta.git": (
        ROOT / "elements" / "gnome-build-meta.bst"
    ),
}

TRACK_RE = re.compile(r"^\s*track:\s*[\"']?([^\"'\s]+)[\"']?\s*$", re.MULTILINE)


def read(path):
    if not path.is_file():
        sys.exit(f"ERROR: expected file not found: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def series_of(track):
    """The literal prefix of a track glob, with the trailing '*' removed.

    `freedesktop-sdk-26.08*` -> `freedesktop-sdk-26.08`
    `gnome-50`               -> `gnome-50`   (no glob; the whole value)
    """
    return track.split("*", 1)[0]


def digits(text):
    """Version-ish digit groups, so an escaped regex and a plain glob compare.

    `^freedesktop-sdk-(?<version>26\\.08\\.[0-9]+)$` -> ['26', '08']
    `freedesktop-sdk-26.08`                          -> ['26', '08']
    `[0-9]+` is dropped: it is the part Renovate fills in, not a series digit.
    """
    stripped = text.replace("\\.", ".").replace("[0-9]+", "")
    return [g for g in re.findall(r"\d+", stripped)]


def main():
    config = json.loads(read(RENOVATE_JSON))
    rules = config.get("packageRules", [])
    failures = []
    checked = 0

    for dep_name, junction_path in JUNCTIONS.items():
        matching = [
            rule
            for rule in rules
            if dep_name in rule.get("matchPackageNames", [])
            and "extractVersion" in rule
        ]
        if not matching:
            failures.append(
                f"renovate.json has no packageRule with an extractVersion for "
                f"{dep_name}; {junction_path.relative_to(ROOT)} would never be bumped"
            )
            continue

        track_match = TRACK_RE.search(read(junction_path))
        if not track_match:
            failures.append(
                f"{junction_path.relative_to(ROOT)} declares no `track:`; "
                "cannot verify the Renovate series against it"
            )
            continue

        series = series_of(track_match.group(1))
        want = digits(series)

        for rule in matching:
            checked += 1
            got = digits(rule["extractVersion"])
            if got != want:
                failures.append(
                    f"{junction_path.relative_to(ROOT)} tracks `{track_match.group(1)}` "
                    f"(series {'.'.join(want) or '<none>'}) but renovate.json filters "
                    f"{dep_name} with extractVersion {rule['extractVersion']!r} "
                    f"(series {'.'.join(got) or '<none>'}). Renovate matches no tag, "
                    "so this junction gets no update PRs."
                )

    if failures:
        for failure in failures:
            print(f"ERROR: {failure}", file=sys.stderr)
        sys.exit(1)

    print(f"OK: {checked} Renovate version filter(s) match their junction `track:` series")


if __name__ == "__main__":
    main()
