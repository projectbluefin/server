"""Read systemd configuration the way systemd does, so tests assert meaning.

A test built on these helpers survives comments, whitespace and key order in
the payload, and fails when a setting systemd would act on changes.
"""

from __future__ import annotations

import fnmatch
import re
import shlex
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

# systemd cannot remove a dependency, so an empty assignment of one of these is
# ignored. An empty Condition*= or Assert*= clears every condition or assert;
# any other empty assignment resets just that key (e.g. ExecStart= in a drop-in).
_DEPENDENCIES = frozenset(
    {
        "After",
        "Before",
        "BindsTo",
        "Conflicts",
        "JoinsNamespaceOf",
        "OnFailure",
        "OnSuccess",
        "PartOf",
        "PropagatesReloadTo",
        "PropagatesStopTo",
        "ReloadPropagatedFrom",
        "Requires",
        "Requisite",
        "StopPropagatedFrom",
        "Upholds",
        "Wants",
    }
)
_EXEC_KEYS = (
    "ExecCondition",
    "ExecStartPre",
    "ExecStart",
    "ExecStartPost",
    "ExecReload",
    "ExecStop",
    "ExecStopPost",
)
_IN_WORD_VARIABLE = re.compile(r"\$\$|\$\{(\w+)\}")


class SystemdFile:
    """A unit, drop-in, .network or other systemd.syntax(7) file.

    ``SystemdFile(unit, *dropins)`` merges the files in the order given, the
    way systemd applies drop-ins after the unit. Repeated keys accumulate.
    """

    def __init__(self, *paths: Path) -> None:
        self.sections: dict[str, dict[str, list[str]]] = {}
        for path in paths:
            self._merge(path)

    def _merge(self, path: Path) -> None:
        section = None
        for line in _logical_lines(path.read_text(encoding="utf-8")):
            if line.startswith("[") and line.endswith("]"):
                section = self.sections.setdefault(line[1:-1], {})
                continue
            key, equals, value = line.partition("=")
            if section is None or not equals:
                raise ValueError(f"{path}: not a Key=value line in a section: {line!r}")
            key, value = key.strip(), value.strip()
            if value:
                section.setdefault(key, []).append(value)
            elif key.startswith(("Condition", "Assert")):
                group = "Condition" if key.startswith("Condition") else "Assert"
                for name in [name for name in section if name.startswith(group)]:
                    del section[name]
            elif key not in _DEPENDENCIES:
                section.pop(key, None)

    def values(self, section: str, key: str) -> list[str]:
        """Every value *key* holds after merging, in assignment order."""
        return list(self.sections.get(section, {}).get(key, []))

    def value(self, section: str, key: str) -> str | None:
        """A single-valued setting: the last assignment wins."""
        values = self.values(section, key)
        return values[-1] if values else None

    def words(self, section: str, key: str) -> list[str]:
        """A space-separated list setting such as After=, Wants= or WantedBy=."""
        return [word for value in self.values(section, key) for word in value.split()]

    def commands(self, key: str = "ExecStart") -> list[list[str]]:
        """Each [Service] *key* command line as argv, Environment= expanded.

        Command prefixes (``-``, ``+``, ``!``...) are dropped; ``$VAR`` as a
        word splits at whitespace, ``${VAR}`` stays one word, ``$$`` is ``$``.
        """
        environment = {}
        for assignment in self.values("Service", "Environment"):
            for pair in shlex.split(assignment):
                name, _, value = pair.partition("=")
                environment[name] = value
        commands = []
        for line in self.values("Service", key):
            argv = []
            for word in shlex.split(line.lstrip("-@:+!|")):
                if re.fullmatch(r"\$\w+", word):
                    argv.extend(environment.get(word[1:], "").split())
                else:
                    argv.append(
                        _IN_WORD_VARIABLE.sub(
                            lambda m: environment.get(m[1], "") if m[1] else "$", word
                        )
                    )
            commands.append(argv)
        return commands

    def all_commands(self) -> list[list[str]]:
        return [argv for key in _EXEC_KEYS for argv in self.commands(key)]


def _logical_lines(text: str) -> Iterable[str]:
    """Non-comment lines with backslash continuations joined, as systemd does."""
    pending = None
    for raw in text.splitlines():
        if raw.strip()[:1] in ("#", ";"):
            continue
        line = raw if pending is None else pending + raw
        if (len(line) - len(line.rstrip("\\"))) % 2:
            pending = line[:-1] + " "
            continue
        pending = None
        if line.strip():
            yield line.strip()
    if pending is not None and pending.strip():
        yield pending.strip()


def preset_rules(path: Path) -> list[tuple[str, str]]:
    """``(verb, unit glob)`` for each rule of a preset file, in order."""
    rules = []
    for line in path.read_text(encoding="utf-8").splitlines():
        words = line.split()
        if words and words[0][0] not in "#;":
            rules.append((words[0], words[1]))
    return rules


def preset(unit: str, files: Iterable[Path]) -> str | None:
    """The verb ``systemctl preset`` applies to *unit*, or None if no rule matches.

    systemd reads preset files in filename order across all directories and the
    first matching rule wins.
    """
    for path in sorted(files, key=lambda path: path.name):
        for verb, pattern in preset_rules(path):
            if fnmatch.fnmatchcase(unit, pattern):
                return verb
    return None


class Tmpfile(NamedTuple):
    type: str
    path: str
    mode: str = "-"
    user: str = "-"
    group: str = "-"
    age: str = "-"
    argument: str = "-"


def tmpfiles(path: Path) -> list[Tmpfile]:
    """The rules of a tmpfiles.d file; omitted trailing fields read as ``-``."""
    return [
        Tmpfile(*line.split(None, 6))
        for line in (raw.strip() for raw in path.read_text(encoding="utf-8").splitlines())
        if line and not line.startswith("#")
    ]
