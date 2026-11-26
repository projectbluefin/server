#!/usr/bin/python3
"""Compose Home Server with the existing Homelab profile; retain one source of defaults."""
import copy
import sys
from pathlib import Path

import yaml


def render_home(home: dict, source_directory: Path) -> dict:
    """Publish a self-contained profile using the real canonical bootstrap."""
    result = copy.deepcopy(home)
    for entry in result.get("storage", {}).get("files", []):
        contents = entry.get("contents", {})
        if "local" in contents:
            contents["inline"] = (source_directory / contents.pop("local")).read_text()
    return result


def compose(home: dict, cluster: dict) -> dict:
    result = copy.deepcopy(cluster)
    # Accounts and keys are always private provisioning, never template examples.
    result.pop("passwd", None)
    for section, groups in home.items():
        if not isinstance(groups, dict):
            result[section] = groups
            continue
        target = result.setdefault(section, {})
        for group, entries in groups.items():
            key = "name" if section == "systemd" else "path"
            merged = {entry[key]: entry for entry in target.get(group, [])}
            merged.update({entry[key]: entry for entry in entries})
            target[group] = list(merged.values())
    return result


if __name__ == "__main__":
    home_source, cluster_source, destination = map(Path, sys.argv[1:])
    home = render_home(yaml.safe_load(home_source.read_text()), home_source.parent)
    cluster = yaml.safe_load(cluster_source.read_text())
    destination.mkdir(parents=True, exist_ok=True)
    (destination / "home-server.bu").write_text(yaml.safe_dump(home, sort_keys=False))
    (destination / "home-server-cluster.bu").write_text(
        yaml.safe_dump(compose(home, cluster), sort_keys=False))
