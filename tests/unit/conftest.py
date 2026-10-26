"""Shared fixtures for the unit tests."""

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / ".github" / "scripts" / "docs-checks.py"


def _required_tool(name: str) -> str:
    path = shutil.which(name)
    if path is None:
        if os.environ.get("CI") == "true":
            pytest.fail(f"{name} is not installed; .github/workflows/unit-tests.yml must install it")
        pytest.skip(f"{name} is not installed")
    return path


@pytest.fixture(scope="session")
def node() -> str:
    return _required_tool("node")


@pytest.fixture(scope="session")
def shellcheck() -> str:
    return _required_tool("shellcheck")


@pytest.fixture(scope="session")
def gpg() -> str:
    return _required_tool("gpg")


@pytest.fixture(scope="session")
def gpgv() -> str:
    return _required_tool("gpgv")


@pytest.fixture(scope="session")
def systemd_analyze() -> str:
    return _required_tool("systemd-analyze")


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Tests marked ``root`` need real ownership changes and privilege drops.

    Unprivileged they skip. The unit job runs them in a separate step with
    ``sudo ... pytest -m root``; there, in CI, an unprivileged run fails
    rather than skips, so a broken sudo cannot pass the job vacuously.
    """
    if item.get_closest_marker("root") is None or os.geteuid() == 0:
        return
    if os.environ.get("CI") == "true" and item.config.getoption("markexpr") == "root":
        pytest.fail("not running as root; .github/workflows/unit-tests.yml must run `-m root` with sudo")
    pytest.skip("requires root")


HOST_MODULE = REPO_ROOT / "files" / "homelab" / "cluster"
# The helpers elements/bluefin-server/os-host.bst links to /usr/bin/bluefin-host.
HOST_HELPERS = (
    "boot-deadline",
    "boot-origin",
    "diskless-update-check",
    "firstboot-credentials",
    "hostname",
    "reboot-lock",
    "repair-etc-modes",
    "sysext-fetch",
    "sysext-modules",
    "update-pending",
    "update-status",
    "update-status-migrate",
)


@pytest.fixture(scope="session")
def host_bin(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory with bluefin-host, built from files/homelab/cluster as
    os-host.bst builds it, and the /usr/libexec/bluefin-* names linked to it."""
    go = _required_tool("go")
    out = tmp_path_factory.mktemp("bluefin-host")
    env = dict(os.environ, CGO_ENABLED="0", GOFLAGS="-mod=vendor -trimpath -buildvcs=false", GOPROXY="off", GOTOOLCHAIN="local")
    subprocess.run([go, "build", "-o", str(out / "bluefin-host"), "./cmd/bluefin-host"], cwd=HOST_MODULE, env=env, check=True)
    for name in HOST_HELPERS:
        (out / f"bluefin-{name}").symlink_to("bluefin-host")
    return out


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
