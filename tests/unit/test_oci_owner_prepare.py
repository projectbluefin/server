"""files/runtimes/bluefin-oci-owner-prepare, run end to end in a sandbox.

bluefin-oci-owner-prepare runs as root before the Homebrew machine starts.
It trusts the owner record only when it is root-owned and unwritable by
others, grants that owner a 65536-wide subordinate UID/GID range in
/etc/subuid and /etc/subgid without colliding with any account or other
range, starts or stops the owner's rootless Podman/Docker user units, and
writes the DOCKER_HOST/CONTAINER_HOST environment the dispatcher reads,
leaving an operator's own file at that path alone.

The script hardcodes host paths and asks for root-only facts, so each test
runs a copy whose host paths point into tmp_path, with PATH shims for the
commands that read or change host state: stat (ownership), getent (the
account databases), chown, loginctl, systemctl and systemd-tmpfiles. The
sourced selection helper is replaced by a stub that takes the Podman/Docker
choice from the environment; tests/unit/test_home_runtime_prepare.py covers
that helper itself.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "files/runtimes/bluefin-oci-owner-prepare"
SOURCE_LINE = 'source "${BASH_SOURCE[0]%/*}/bluefin-oci-features"'
# Every host path the script reads or writes. Each one is redirected under the
# sandbox root; a path missing from the script means it changed and this
# harness needs updating, so the copy refuses to build rather than touch /.
HOST_PATHS = (
    "/var/lib/bluefin-homebrew/owner",
    "/etc/subuid",
    "/etc/subgid",
    "/run/lock",
    "/sys/fs/cgroup",
    "/proc/sys/",
    "/usr/bin/",
    "/run/user/",
    "/usr/lib/bluefin/",
    "/etc/bluefin-homebrew",
)
UID = 1000
OWNER = "alice"
MANAGED = "# Managed by bluefin-oci-owner-prepare"

FEATURES_STUB = """\
set -euo pipefail
fail() { printf '%s: %s\\n' "${0##*/}" "$*" >&2; exit 1; }
podman=${TEST_PODMAN:-false}
docker=${TEST_DOCKER:-false}
feature_selection() { :; }
"""

STAT_SHIM = """\
#!/bin/bash
# Ownership comes from $STAT_UIDS ("<path> <uid>" lines, default 0) because
# the sandbox files are owned by whoever runs the tests, never by root.
if [[ $1 == -c && $2 == %u ]]; then
    [[ -e $3 || -L $3 ]] || { echo "stat: cannot statx '$3'" >&2; exit 1; }
    while read -r path uid; do
        [[ $path == "$3" ]] && { echo "$uid"; exit 0; }
    done < "$STAT_UIDS"
    echo 0
    exit 0
fi
exec {real} "$@"
"""

GETENT_SHIM = """\
#!/bin/bash
db=$SANDBOX/db/$1
[[ -f $db ]] || exit 2
if [[ $# == 1 ]]; then
    cat "$db"
    exit 0
fi
while IFS= read -r line; do
    IFS=: read -r name _ id _ <<< "$line"
    [[ $2 == "$name" || $2 == "$id" ]] && { echo "$line"; exit 0; }
done < "$db"
exit 2
"""

RECORDING_SHIM = """\
#!/bin/bash
printf '%s %s\\n' "${0##*/}" "$*" >> "$SANDBOX/calls"
if [[ ${0##*/} == systemctl ]]; then
    for arg; do
        case $arg in
            is-active) exit "${TEST_USER_MANAGER_INACTIVE:-0}" ;;
            cat) exit "${TEST_UNIT_ABSENT:-0}" ;;
        esac
    done
fi
exit 0
"""


class Sandbox:
    def __init__(self, root: Path):
        self.root = root
        self.stat_uids: dict[str, int] = {}
        self.env = {
            "PATH": f"{root / 'shims'}:{os.environ['PATH']}",
            "SANDBOX": str(root),
            "STAT_UIDS": str(root / "stat-uids"),
            "LC_ALL": "C",
        }

    def path(self, host_path: str) -> Path:
        return self.root / host_path.lstrip("/")

    def write(self, host_path: str, text: str, mode: int = 0o644) -> Path:
        target = self.path(host_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        target.chmod(mode)
        return target

    def owned_by(self, host_path: str, uid: int) -> None:
        self.stat_uids[str(self.path(host_path))] = uid

    def calls(self) -> list[str]:
        calls = self.root / "calls"
        return calls.read_text().splitlines() if calls.exists() else []

    def run(self, *args: str, podman: bool = False, docker: bool = False, **env: str):
        (self.root / "stat-uids").write_text(
            "".join(f"{path} {uid}\n" for path, uid in self.stat_uids.items())
        )
        return subprocess.run(
            ["bash", str(self.root / "bluefin-oci-owner-prepare"), *args],
            env=self.env | {"TEST_PODMAN": str(podman).lower(), "TEST_DOCKER": str(docker).lower()} | env,
            capture_output=True,
            text=True,
            timeout=30,
        )


@pytest.fixture
def sandbox(tmp_path: Path) -> Sandbox:
    box = Sandbox(tmp_path)
    script = SCRIPT.read_text()
    assert SOURCE_LINE in script, "bluefin-oci-owner-prepare no longer sources bluefin-oci-features this way"
    for host_path in HOST_PATHS:
        assert host_path in script, f"bluefin-oci-owner-prepare no longer uses {host_path}"
        script = script.replace(host_path, f"{tmp_path}{host_path}")
    script = script.replace(SOURCE_LINE, f'source "{tmp_path}/features-stub"')
    (tmp_path / "bluefin-oci-owner-prepare").write_text(script)
    (tmp_path / "features-stub").write_text(FEATURES_STUB)

    shims = tmp_path / "shims"
    shims.mkdir()
    real_stat = shutil.which("stat")
    assert real_stat is not None
    for name, body in {
        "stat": STAT_SHIM.replace("{real}", real_stat),
        "getent": GETENT_SHIM,
        **{name: RECORDING_SHIM for name in ("chown", "loginctl", "systemctl", "systemd-tmpfiles")},
    }.items():
        (shims / name).write_text(body)
        (shims / name).chmod(0o755)

    box.write("/db/passwd", f"root:x:0:0::/root:/bin/bash\n{OWNER}:x:{UID}:{UID}::/var/home/{OWNER}:/bin/bash\n")
    box.write("/db/group", f"root:x:0:\n{OWNER}:x:{UID}:\n")
    box.path("/etc").mkdir()
    box.write("/var/lib/bluefin-homebrew/owner", f"{UID}:{UID}\n")
    box.write("/sys/fs/cgroup/cgroup.controllers", "cpu memory pids\n")
    for helper in ("newuidmap", "newgidmap"):
        box.write(f"/usr/bin/{helper}", "#!/bin/sh\n", 0o755)
    for engine in ("podman", "docker"):
        endpoint = f"/run/user/{UID}/bluefin-{engine}"
        box.path(endpoint).mkdir(parents=True)
        box.path(endpoint).chmod(0o700)
        box.owned_by(endpoint, UID)
    box.write("/usr/lib/bluefin/podman/podman", "#!/bin/sh\n", 0o755)
    box.write("/usr/lib/bluefin/docker/bin/dockerd", "#!/bin/sh\n", 0o755)
    return box


def env_file(box: Sandbox) -> Path:
    return box.path(f"/etc/bluefin-homebrew/runtime.{UID}.env")


def assert_refused(result, message: str) -> None:
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"bluefin-oci-owner-prepare: {message}" in result.stderr


# --- arguments and owner record ---------------------------------------------


def test_refuses_any_argument(sandbox):
    result = sandbox.run("--now")
    assert result.returncode == 1
    assert result.stderr == "usage: bluefin-oci-owner-prepare\n"
    assert sandbox.calls() == []


def test_refuses_a_symlinked_owner_record(sandbox):
    record = sandbox.path("/var/lib/bluefin-homebrew/owner")
    target = sandbox.write("/elsewhere/owner", f"{UID}:{UID}\n")
    record.unlink()
    record.symlink_to(target)
    assert_refused(sandbox.run(), "owner record must be root-owned and not a symlink")


def test_refuses_an_owner_record_not_owned_by_root(sandbox):
    sandbox.owned_by("/var/lib/bluefin-homebrew/owner", UID)
    assert_refused(sandbox.run(), "owner record must be root-owned and not a symlink")


@pytest.mark.parametrize("mode", [0o664, 0o646], ids=["group-writable", "world-writable"])
def test_refuses_a_writable_owner_record(sandbox, mode):
    sandbox.path("/var/lib/bluefin-homebrew/owner").chmod(mode)
    assert_refused(sandbox.run(), "owner record must not be group/world writable")


@pytest.mark.parametrize("record", ["0:0\n", "alice:1000\n", "1000\n", "1000:x\n"])
def test_refuses_a_root_or_malformed_owner_record(sandbox, record):
    sandbox.write("/var/lib/bluefin-homebrew/owner", record)
    assert_refused(sandbox.run(), "owner record must contain non-root UID:GID")


def test_refuses_an_owner_record_naming_no_account(sandbox):
    sandbox.write("/var/lib/bluefin-homebrew/owner", "2000:2000\n")
    assert_refused(sandbox.run(), "owner account does not exist")


def test_refuses_an_owner_whose_primary_group_changed(sandbox):
    sandbox.write("/var/lib/bluefin-homebrew/owner", f"{UID}:{UID + 1}\n")
    assert_refused(sandbox.run(), "owner identity changed")


def test_refuses_an_account_name_that_is_not_a_login_name(sandbox):
    sandbox.write("/db/passwd", f"-rf:x:{UID}:{UID}::/var/home/x:/bin/bash\n")
    assert_refused(sandbox.run(), "invalid owner account name")


# --- rootless engine prerequisites ------------------------------------------


def test_refuses_rootless_engines_without_cgroup_v2(sandbox):
    sandbox.path("/sys/fs/cgroup/cgroup.controllers").unlink()
    assert_refused(sandbox.run(podman=True), "rootless runtimes require cgroup v2")


@pytest.mark.parametrize(
    ("knob", "value"),
    [("/proc/sys/user/max_user_namespaces", "0\n"), ("/proc/sys/kernel/unprivileged_userns_clone", "0\n")],
    ids=["max_user_namespaces", "unprivileged_userns_clone"],
)
def test_refuses_rootless_engines_when_user_namespaces_are_off(sandbox, knob, value):
    sandbox.write(knob, value)
    assert_refused(sandbox.run(docker=True), "unprivileged user namespaces are disabled")


def test_accepts_enabled_user_namespace_knobs(sandbox):
    sandbox.write("/proc/sys/user/max_user_namespaces", "63000\n")
    sandbox.write("/proc/sys/kernel/unprivileged_userns_clone", "1\n")
    result = sandbox.run(podman=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("helper", ["newuidmap", "newgidmap"])
def test_refuses_id_map_helpers_not_owned_by_root(sandbox, helper):
    sandbox.owned_by(f"/usr/bin/{helper}", UID)
    assert_refused(sandbox.run(podman=True), f"{helper} must be a root-owned FSDK executable in the host image")


def test_refuses_a_missing_id_map_helper(sandbox):
    sandbox.path("/usr/bin/newgidmap").unlink()
    assert_refused(sandbox.run(podman=True), "newgidmap must be a root-owned FSDK executable in the host image")


# --- subordinate ID ranges --------------------------------------------------


def test_grants_the_owner_a_fresh_range_and_starts_the_user_manager(sandbox):
    result = sandbox.run(podman=True)
    assert result.returncode == 0, result.stderr
    assert sandbox.path("/etc/subuid").read_text() == f"\n{OWNER}:100000:65536\n"
    assert sandbox.path("/etc/subgid").read_text() == f"\n{OWNER}:100000:65536\n"
    calls = sandbox.calls()
    assert f"loginctl enable-linger {OWNER}" in calls
    assert f"systemctl start user@{UID}.service" in calls
    assert calls.index(f"loginctl enable-linger {OWNER}") < calls.index(f"systemctl start user@{UID}.service")


def test_places_the_new_range_after_existing_ranges_and_account_ids(sandbox):
    sandbox.write("/db/passwd", sandbox.path("/db/passwd").read_text() + "big:x:300000:300000::/:/bin/false\n")
    sandbox.write("/etc/subuid", "# keep\nbob:100000:65536\n")
    sandbox.write("/etc/subgid", "bob:100000:65536\n")
    result = sandbox.run(docker=True)
    assert result.returncode == 0, result.stderr
    # subuid: the passwd account 300000 sits above bob's range, so start past it.
    assert sandbox.path("/etc/subuid").read_text() == f"# keep\nbob:100000:65536\n\n{OWNER}:300001:65536\n"
    # subgid reads the group database, where nothing sits above bob's range.
    assert sandbox.path("/etc/subgid").read_text() == f"bob:100000:65536\n\n{OWNER}:165536:65536\n"


def test_reuses_an_existing_owner_range_and_is_idempotent(sandbox):
    for host_path in ("/etc/subuid", "/etc/subgid"):
        sandbox.write(host_path, f"{UID}:200000:65536\nbob:100000:65536\n")
    for _ in range(2):
        result = sandbox.run(podman=True)
        assert result.returncode == 0, result.stderr
    for host_path in ("/etc/subuid", "/etc/subgid"):
        assert sandbox.path(host_path).read_text() == f"{UID}:200000:65536\nbob:100000:65536\n"


def test_refuses_an_owner_range_smaller_than_65536(sandbox):
    sandbox.write("/etc/subuid", f"{OWNER}:100000:65535\n")
    assert_refused(sandbox.run(podman=True), f"{OWNER} needs at least 65536 subordinate IDs in {sandbox.path('/etc/subuid')}")


@pytest.mark.parametrize(
    "line",
    ["bob:100000\n", "bob:x:65536\n", "bob:100000:65536:extra\n", "bob:-1:65536\n"],
    ids=["two-fields", "non-numeric", "four-fields", "negative"],
)
def test_refuses_a_malformed_map_entry(sandbox, line):
    sandbox.write("/etc/subuid", line)
    assert_refused(sandbox.run(podman=True), f"malformed {sandbox.path('/etc/subuid')} entry")


@pytest.mark.parametrize(
    "line",
    ["bob:0:65536\n", "bob:100000:0\n", "bob:4294967295:1\n"],
    ids=["zero-start", "zero-count", "past-32-bits"],
)
def test_refuses_an_out_of_range_map_entry(sandbox, line):
    sandbox.write("/etc/subuid", line)
    assert_refused(sandbox.run(podman=True), f"invalid {sandbox.path('/etc/subuid')} range")


def test_refuses_a_range_that_covers_a_real_account(sandbox):
    sandbox.write("/etc/subuid", "bob:500:65536\n")
    assert_refused(
        sandbox.run(podman=True),
        f"{sandbox.path('/etc/subuid')} subordinate range overlaps an existing passwd ID",
    )


def test_refuses_an_owner_range_that_overlaps_another_identity(sandbox):
    sandbox.write("/etc/subgid", f"bob:100000:65536\n{OWNER}:150000:65536\n")
    assert_refused(sandbox.run(podman=True), f"{sandbox.path('/etc/subgid')} owner range overlaps another identity")


def test_refuses_when_no_subordinate_id_space_is_left(sandbox):
    sandbox.write("/etc/subuid", "bob:4294900000:60000\n")
    assert_refused(sandbox.run(podman=True), f"no subordinate ID space in {sandbox.path('/etc/subuid')}")


def test_refuses_a_symlinked_map(sandbox):
    target = sandbox.write("/elsewhere/subuid", "")
    sandbox.path("/etc/subuid").symlink_to(target)
    assert_refused(sandbox.run(podman=True), f"{sandbox.path('/etc/subuid')} must not be a symlink")
    assert target.read_text() == ""


def test_refuses_a_map_not_owned_by_root(sandbox):
    sandbox.write("/etc/subgid", "")
    sandbox.owned_by("/etc/subgid", UID)
    assert_refused(sandbox.run(podman=True), f"{sandbox.path('/etc/subgid')} must be root-owned")


def test_refuses_a_writable_map(sandbox):
    sandbox.write("/etc/subuid", "", 0o666)
    assert_refused(sandbox.run(podman=True), f"{sandbox.path('/etc/subuid')} must not be group/world writable")


def test_leaves_maps_and_user_manager_alone_when_no_engine_is_selected(sandbox):
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert not sandbox.path("/etc/subuid").exists()
    assert not sandbox.path("/etc/subgid").exists()
    assert not any(call.startswith(("loginctl", "systemctl start")) for call in sandbox.calls())


# --- endpoints and engines --------------------------------------------------


@pytest.mark.parametrize("engine", ["podman", "docker"])
def test_refuses_a_missing_endpoint_directory(sandbox, engine):
    shutil.rmtree(sandbox.path(f"/run/user/{UID}/bluefin-{engine}"))
    assert_refused(sandbox.run(), f"{engine} owner endpoint directory is missing or not private")


def test_refuses_an_endpoint_directory_others_can_read(sandbox):
    sandbox.path(f"/run/user/{UID}/bluefin-docker").chmod(0o750)
    assert_refused(sandbox.run(), "docker owner endpoint directory is missing or not private")


def test_refuses_an_endpoint_directory_owned_by_someone_else(sandbox):
    sandbox.owned_by(f"/run/user/{UID}/bluefin-podman", 0)
    assert_refused(sandbox.run(), "podman owner endpoint directory is missing or not private")


def test_refuses_a_symlinked_endpoint_directory(sandbox):
    endpoint = sandbox.path(f"/run/user/{UID}/bluefin-podman")
    endpoint.rmdir()
    elsewhere = sandbox.path("/elsewhere/podman")
    elsewhere.mkdir(parents=True)
    elsewhere.chmod(0o700)
    endpoint.symlink_to(elsewhere)
    sandbox.owned_by(f"/run/user/{UID}/bluefin-podman", UID)
    assert_refused(sandbox.run(), "podman owner endpoint directory is missing or not private")


@pytest.mark.parametrize(
    ("engine", "binary", "message"),
    [
        ("podman", "/usr/lib/bluefin/podman/podman", "selected Podman sysext is not merged"),
        ("docker", "/usr/lib/bluefin/docker/bin/dockerd", "selected Docker sysext is not merged"),
    ],
)
def test_refuses_a_selected_engine_whose_sysext_is_absent(sandbox, engine, binary, message):
    sandbox.path(binary).unlink()
    assert_refused(sandbox.run(**{engine: True}), message)


def test_enables_selected_units_and_disables_deselected_ones(sandbox):
    result = sandbox.run(podman=True)
    assert result.returncode == 0, result.stderr
    machine = f"--user --machine={OWNER}@.host"
    calls = sandbox.calls()
    assert f"systemd-tmpfiles --create {sandbox.path('/usr/lib/bluefin/podman/tmpfiles.conf')}" in calls
    assert f"systemctl {machine} daemon-reload" in calls
    assert f"systemctl {machine} enable --now bluefin-podman.socket" in calls
    assert f"systemctl {machine} disable --now bluefin-docker.service" in calls
    assert not any("stop bluefin-podman.service" in call for call in calls)


def test_stops_the_podman_service_when_podman_is_deselected(sandbox):
    result = sandbox.run(docker=True)
    assert result.returncode == 0, result.stderr
    machine = f"--user --machine={OWNER}@.host"
    calls = sandbox.calls()
    assert f"systemctl {machine} enable --now bluefin-docker.service" in calls
    assert f"systemctl {machine} disable --now bluefin-podman.socket" in calls
    assert f"systemctl {machine} stop bluefin-podman.service" in calls
    assert not any(call.startswith("systemd-tmpfiles") for call in calls)


def test_does_not_disable_units_the_user_manager_does_not_have(sandbox):
    result = sandbox.run(TEST_UNIT_ABSENT="1")
    assert result.returncode == 0, result.stderr
    assert not any(" disable " in call or " stop " in call for call in sandbox.calls())


def test_skips_user_units_when_the_user_manager_is_not_running(sandbox):
    result = sandbox.run(podman=True, TEST_USER_MANAGER_INACTIVE="3")
    assert result.returncode == 0, result.stderr
    assert not any("--machine=" in call for call in sandbox.calls())


# --- runtime environment ----------------------------------------------------


@pytest.mark.parametrize(
    ("podman", "docker", "backend"),
    [(True, False, "podman"), (False, True, "docker"), (True, True, "docker"), (False, False, "podman")],
)
def test_writes_the_managed_environment_for_the_selected_backend(sandbox, podman, docker, backend):
    result = sandbox.run(podman=podman, docker=docker)
    assert result.returncode == 0, result.stderr
    assert env_file(sandbox).read_text() == (
        f"{MANAGED}\n"
        f"DOCKER_HOST=unix:///run/bluefin-engines/{UID}/{backend}/api.sock\n"
        f"CONTAINER_HOST=unix:///run/bluefin-engines/{UID}/podman/api.sock\n"
    )
    assert env_file(sandbox).stat().st_mode & 0o777 == 0o644
    assert sandbox.path("/etc/bluefin-homebrew").stat().st_mode & 0o777 == 0o755
    assert f"chown root:root {env_file(sandbox)}.new" in sandbox.calls()
    assert not Path(f"{env_file(sandbox)}.new").exists()


def test_rewrites_its_own_environment_when_the_selection_changes(sandbox):
    assert sandbox.run(podman=True).returncode == 0
    result = sandbox.run(docker=True)
    assert result.returncode == 0, result.stderr
    assert f"/{UID}/docker/api.sock" in env_file(sandbox).read_text()


def test_preserves_an_operator_environment_at_the_same_path(sandbox):
    operator = "DOCKER_HOST=tcp://build-box:2375\n"
    sandbox.write(f"/etc/bluefin-homebrew/runtime.{UID}.env", operator)
    result = sandbox.run(docker=True)
    assert result.returncode == 0, result.stderr
    assert env_file(sandbox).read_text() == operator
    assert not any(call.startswith("chown") for call in sandbox.calls())


def test_refuses_a_symlinked_environment_directory(sandbox):
    elsewhere = sandbox.path("/elsewhere/config")
    elsewhere.mkdir(parents=True)
    sandbox.path("/etc/bluefin-homebrew").symlink_to(elsewhere)
    assert_refused(sandbox.run(), "runtime environment directory must not be a symlink")
    assert list(elsewhere.iterdir()) == []


def test_refuses_an_environment_directory_not_owned_by_root(sandbox):
    sandbox.path("/etc/bluefin-homebrew").mkdir(parents=True)
    sandbox.owned_by("/etc/bluefin-homebrew", UID)
    assert_refused(sandbox.run(), "runtime environment directory must be root-owned")


def test_refuses_a_writable_environment_directory(sandbox):
    sandbox.path("/etc/bluefin-homebrew").mkdir(parents=True)
    sandbox.path("/etc/bluefin-homebrew").chmod(0o775)
    assert_refused(sandbox.run(), "runtime environment directory must not be group/world writable")


def test_refuses_a_symlinked_environment_file(sandbox):
    target = sandbox.write("/elsewhere/env", f"{MANAGED}\n")
    sandbox.path("/etc/bluefin-homebrew").mkdir(parents=True)
    env_file(sandbox).symlink_to(target)
    assert_refused(sandbox.run(), "runtime environment must be root-owned and not a symlink")
    assert target.read_text() == f"{MANAGED}\n"


def test_refuses_an_environment_file_not_owned_by_root(sandbox):
    sandbox.write(f"/etc/bluefin-homebrew/runtime.{UID}.env", f"{MANAGED}\n")
    sandbox.owned_by(f"/etc/bluefin-homebrew/runtime.{UID}.env", UID)
    assert_refused(sandbox.run(), "runtime environment must be root-owned and not a symlink")


def test_refuses_a_writable_environment_file(sandbox):
    sandbox.write(f"/etc/bluefin-homebrew/runtime.{UID}.env", f"{MANAGED}\n", 0o666)
    assert_refused(sandbox.run(), "runtime environment must not be group/world writable")
