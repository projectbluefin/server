"""The guest scripts the dogfood scripts write as heredocs (the probes, and
the screen, noise, update and SSH helpers) pass a bash syntax check
(`bash -n`); none of them is run here.

A probe with a syntax error runs up to the error inside the guest and the
run then times out, far from the cause; shellcheck of the host script never
sees the heredoc's contents.

A guest script is a heredoc written to a `*.probe` or `*.sh` file, or a
`<<'PROBE'` fragment appended to one. An unquoted heredoc is checked as the
host writes it: with `\\$`, `\\``, `\\\\` and `\\<newline>` unescaped (the
host's own `${var}` expansions are valid bash as they stand).
"""


import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
# <<TAG, <<'TAG', <<-TAG; not a <<< here-string.
HEREDOC = re.compile(r"""(?<!<)<<-?\s*(['"]?)(\w+)\1""")
# The file a line writes: cat > "${state}/x.probe" <<'EOF', or a group's
# { ...; } > "${state}/x.probe"; the last one on the line.
TARGET = re.compile(r'>\s*"[^"]*/([\w.-]+)"')
UNESCAPE = re.compile(r"\\([$`\\\n])")


def heredocs(text: str) -> list[tuple[int, str, str, bool, str]]:
    """(line, target file or "", tag, quoted, body) for every heredoc a
    host-level line of a script opens, bodies taken in order."""
    lines = text.splitlines(keepends=True)
    found = []
    i = 0
    while i < len(lines):
        line = lines[i]
        i += 1
        opened = HEREDOC.findall(line)
        targets = TARGET.findall(line)
        target = targets[-1] if targets else ""
        for quote, tag in opened:
            start, body = i, []
            while i < len(lines) and lines[i].rstrip("\n") != tag:
                body.append(lines[i])
                i += 1
            i += 1  # the terminator
            found.append((start, target, tag, bool(quote), "".join(body)))
    return found


def is_guest_script(target: str, tag: str) -> bool:
    return target.endswith((".probe", ".sh")) or tag == "PROBE"


def as_written(body: str, quoted: bool) -> str:
    """The body as the host writes it: an unquoted heredoc unescapes."""
    return body if quoted else UNESCAPE.sub(lambda m: "" if m[1] == "\n" else m[1], body)


PROBES = [
    (f"{script.name}:{line}:{target or '-'}<<{tag}", as_written(body, quoted))
    for script in sorted(SCRIPTS.glob("dogfood-*.sh"))
    for line, target, tag, quoted, body in heredocs(script.read_text(encoding="utf-8"))
    if is_guest_script(target, tag)
]


def test_the_probes_are_found() -> None:
    found = {re.sub(r":\d+:", ":", probe) for probe, _ in PROBES}
    for expected in (
        "dogfood-homelab-templates.sh:cp.probe<<EOF",
        "dogfood-diskless.sh:probe.sh<<PROBE",
        "dogfood-installer.sh:screen.sh<<SCREEN",
        "dogfood-installer.sh:noise.sh<<NOISE",
        "dogfood-installer.sh:update.sh<<UPDATE",
        "dogfood-installer.sh:ssh.sh<<SSH",
        "dogfood-installer.sh:-<<PROBE",
        "dogfood-install.sh:break.probe<<BREAK",
        "dogfood-install.sh:rollback.probe<<GATE",
        "dogfood-install.sh:rollback.probe<<AFTER",
        # Unquoted: checked after the host's unescaping.
        "dogfood-kubeadm.sh:kubeadm.probe<<EOF",
        "dogfood-nvidia.sh:fetch.probe<<EOF",
        "dogfood-nvidia.sh:nvidia.probe<<EOF",
    ):
        assert expected in found, sorted(found)


def test_unit_files_and_other_heredocs_are_not_checked_as_bash() -> None:
    names = {probe.split(":", 2)[2] for probe, _ in PROBES}
    skipped = (".service<<UNIT", ".service<<EOF", ".conf<<EOF", ".ign<<EOF", "<<PY", "<<SWITCH", "<<PVC")
    assert not [n for n in names if n.endswith(skipped)], names


@pytest.mark.parametrize(("probe", "body"), PROBES, ids=[p for p, _ in PROBES])
def test_probe_passes_bash_syntax_check(probe: str, body: str) -> None:
    result = subprocess.run(["bash", "-n"], input=body, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"{probe}: {result.stderr}"
