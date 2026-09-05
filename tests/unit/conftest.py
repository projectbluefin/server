"""Shared fixtures for the docs-checks unit tests."""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "docs-checks.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("docs_checks", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["docs_checks"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def docs_checks(tmp_path):
    """Fresh module instance rooted at an isolated tmp tree.

    The script keeps ``errors``/``warnings`` in module-level globals and derives
    ``ROOT`` from its own location, so each test gets a re-imported copy with the
    path constants repointed at ``tmp_path``.
    """
    module = _load_module()
    module.ROOT = tmp_path
    module.DOCS_DIR = tmp_path / "docs"
    module.SKILLS_DIR = module.DOCS_DIR / "skills"
    module.SKILLS_DIR.mkdir(parents=True)
    module.errors.clear()
    module.warnings.clear()
    yield module
    sys.modules.pop("docs_checks", None)
