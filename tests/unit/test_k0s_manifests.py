"""The k0s sysext's controller and worker units."""

import posixpath
from pathlib import Path

from _systemd import SystemdFile

ROOT = Path(__file__).resolve().parents[2]


def test_k0s_service_unit():
    unit = ROOT / "files" / "k0s" / "sysext" / "k0scontroller.service"
    assert unit.is_file(), "k0scontroller.service missing"
    controller = SystemdFile(unit)
    # The default command line, K0S_CONTROLLER_ARGS from Environment= expanded:
    # a single-node controller that also runs the workloads.
    commands = controller.commands()
    assert len(commands) == 1
    argv = commands[0]
    assert posixpath.basename(argv[0]) == "k0s" and argv[1] == "controller"
    assert {"--enable-worker", "--single", "--disable-components=helm,autopilot"} <= set(argv[2:])
    assert "!/etc/k0s/token" in controller.values("Unit", "ConditionPathExists")


def test_k0s_worker_unit_joins_with_the_token_file():
    worker = SystemdFile(ROOT / "files" / "k0s" / "sysext" / "k0sworker.service")
    commands = worker.commands()
    assert len(commands) == 1
    argv = commands[0]
    assert posixpath.basename(argv[0]) == "k0s"
    assert argv[1:4] == ["worker", "--token-file", "/etc/k0s/token"]
    assert "/etc/k0s/token" in worker.values("Unit", "ConditionPathExists")
