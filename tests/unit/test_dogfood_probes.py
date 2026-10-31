"""The guest probes the dogfood scripts write (quoted heredocs) pass a bash
syntax check (`bash -n`); none of them is run here.

A probe with a syntax error runs up to the error inside the guest and the
run then times out, far from the cause; shellcheck of the host script never
sees the heredoc's contents.
"""


import re
import subprocess
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
PROBE = re.compile(r"""^cat > "\$\{state\}/([\w-]+\.probe)" <<'EOF'\n(.*?)^EOF$""", re.M | re.S)
PROBES = [(f"{script.name}:{name}", body)
          for script in sorted(SCRIPTS.glob("dogfood-*.sh"))
          for name, body in PROBE.findall(script.read_text(encoding="utf-8"))]


def test_the_probes_are_found() -> None:
    assert "dogfood-homelab-templates.sh:cp.probe" in dict(PROBES)


@pytest.mark.parametrize(("probe", "body"), PROBES, ids=[p for p, _ in PROBES])
def test_probe_passes_bash_syntax_check(probe: str, body: str) -> None:
    result = subprocess.run(["bash", "-n"], input=body, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f"{probe}: {result.stderr}"
