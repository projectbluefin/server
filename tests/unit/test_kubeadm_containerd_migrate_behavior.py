"""Executed coverage for files/kubeadm/sysext/bluefin-kubeadm-containerd-migrate.

The kubeadm sysext ships this helper and runs it from containerd.service
ExecStartPre to backfill the containerd `imports` glob on an installed node
whose /etc/containerd/config.toml predates the glob (review backlog
issue #351: tmpfiles `C` only seeds when absent, so the seeded copy survives
forever). The helper is idempotent: a config that already declares `imports`
is left alone, no mtime change, so DaemonSet / kured watchers stay quiet.
"""


import os
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HELPER = REPO_ROOT / "files" / "kubeadm" / "sysext" / "bluefin-kubeadm-containerd-migrate"
SHIPPED_CONFIG = REPO_ROOT / "files" / "kubeadm" / "sysext" / "config.toml"

EXPECTED_IMPORTS = (
    'imports = ["/usr/share/bluefin/containerd/conf.d/*.toml", '
    '"/etc/containerd/conf.d/*.toml"]'
)


def _run(config: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(HELPER), f"--config={config}"],
        capture_output=True,
        text=True,
        env=dict(os.environ),
    )


def _seeded_kubeadm_config() -> str:
    # Mirrors files/kubeadm/sysext/config.toml as it was before `imports`
    # landed: the version the tmpfiles `C` rule still copies on every node
    # that was installed before PR #350. The migrator must add `imports`
    # so drop-ins (NVIDIA Container Toolkit's `nvidia` handler, node
    # overrides in /etc/containerd/conf.d) deep-merge into the kubeadm
    # containerd config.
    return (
        'version = 3\n'
        'root = "/var/lib/containerd"\n'
        'state = "/run/containerd"\n'
        '\n'
        '[grpc]\n'
        '  address = "/run/containerd/containerd.sock"\n'
        '\n'
        '[plugins]\n'
        '  [plugins."io.containerd.cri.v1.images"]\n'
        '    snapshotter = "overlayfs"\n'
        '\n'
        '    [plugins."io.containerd.cri.v1.images".pinned_images]\n'
        '      sandbox = "registry.k8s.io/pause:3.10.1"\n'
        '\n'
        '    [plugins."io.containerd.cri.v1.images".registry]\n'
        '      config_path = "/etc/containerd/certs.d"\n'
        '\n'
        '  [plugins."io.containerd.cri.v1.runtime"]\n'
        '    ignore_image_defined_volumes = true\n'
        '\n'
        '    [plugins."io.containerd.cri.v1.runtime".containerd]\n'
        '      default_runtime_name = "runc"\n'
        '\n'
        '      [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc]\n'
        '        runtime_type = "io.containerd.runc.v2"\n'
        '\n'
        '        [plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc.options]\n'
        '          BinaryName = "/usr/bin/runc"\n'
        '          SystemdCgroup = true\n'
        '\n'
        '    [plugins."io.containerd.cri.v1.runtime".cni]\n'
        '      bin_dirs = ["/opt/cni/bin", "/usr/libexec/cni"]\n'
        '      conf_dir = "/etc/cni/net.d"\n'
    )


def test_helper_is_bash_that_passes_syntax() -> None:
    assert HELPER.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
    subprocess.run(["bash", "-n", str(HELPER)], check=True)


def test_prepends_imports_to_a_pre_existing_config_without_them(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(_seeded_kubeadm_config(), encoding="utf-8")
    original = config.read_text(encoding="utf-8")

    result = _run(config)

    assert result.returncode == 0, result.stderr
    migrated = config.read_text(encoding="utf-8")
    # The original content is preserved as a contiguous block; the migration
    # prepends the imports block at line 1, so the file is the seed with the
    # block in front of it. containerd's TOML loader only consults a
    # top-level `imports`, so a substring check is insufficient — verify
    # the parsed structure carries the imports at the top level and nowhere
    # else.
    assert EXPECTED_IMPORTS in migrated
    # Migrator stamps a blame line so on-disk diffs make it obvious where the
    # line came from without `git log` against /etc/containerd.
    assert "bluefin-kubeadm-containerd-migrate" in migrated
    parsed = tomllib.loads(migrated)
    assert parsed["imports"] == [
        "/usr/share/bluefin/containerd/conf.d/*.toml",
        "/etc/containerd/conf.d/*.toml",
    ]
    # Imports must not be nested under any [plugins.*] table — that placement
    # is what containerd ignores. Walk every nested table (skipping the top
    # level, which legitimately carries `imports`) and assert no `imports`
    # key appears below it.
    def _assert_no_nested_imports(table: object) -> None:
        if isinstance(table, dict):
            for value in table.values():
                if isinstance(value, dict):
                    assert "imports" not in value, (
                        f"imports nested under a subtable is not consulted "
                        f"by containerd: {value!r}"
                    )
                    _assert_no_nested_imports(value)
    _assert_no_nested_imports(parsed)
    # Sanity: the seeded content survives untouched (the migration must
    # not lose any table the kubeadm sysext or operators configured).
    assert 'address = "/run/containerd/containerd.sock"' in migrated
    assert "registry.k8s.io/pause:3.10.1" in migrated
    # The block lands at the top of the file, so the blame comment precedes
    # every line the seed carried.
    assert migrated.startswith("# Added by bluefin-kubeadm-containerd-migrate")
    # Sanity: the original file's content is still all there (none of the
    # seeded lines are dropped or reordered).
    for line in original.strip().splitlines():
        assert line in migrated.splitlines()


def test_idempotent_when_imports_already_present(tmp_path: Path) -> None:
    # Top-level (ahead of every table header) is where containerd reads
    # `imports`, so this config needs nothing: the migrator must not rewrite
    # it.
    config = tmp_path / "config.toml"
    config.write_text(EXPECTED_IMPORTS + "\n\n" + _seeded_kubeadm_config(), encoding="utf-8")
    before_mtime = config.stat().st_mtime_ns
    before_inode = config.stat().st_ino
    expected = config.read_text(encoding="utf-8")

    result = _run(config)

    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding="utf-8") == expected
    # mtime and inode must not change: DaemonSets and kured watch the file,
    # and a false trigger on every containerd restart would be a regression.
    assert config.stat().st_mtime_ns == before_mtime
    assert config.stat().st_ino == before_inode


def test_shipped_config_is_left_untouched(tmp_path: Path) -> None:
    # Fresh installs and diskless boots seed the shipped config, which already
    # carries the exact line the helper backfills: seeding it must not trigger
    # a rewrite, and a migrated legacy node must import the same globs.
    shipped = SHIPPED_CONFIG.read_text(encoding="utf-8")
    assert EXPECTED_IMPORTS in shipped.splitlines()
    config = tmp_path / "config.toml"
    config.write_text(shipped, encoding="utf-8")
    before = config.stat()

    result = _run(config)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert config.read_text(encoding="utf-8") == shipped
    assert (config.stat().st_mtime_ns, config.stat().st_ino) == (before.st_mtime_ns, before.st_ino)


def test_existing_config_with_user_overrides_is_preserved(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    user_line = 'sandbox_image = "registry.example.com/pause:3.10.1"'
    config.write_text(_seeded_kubeadm_config().replace(
        'sandbox = "registry.k8s.io/pause:3.10.1"',
        'sandbox = "registry.k8s.io/pause:3.10.1"\n      ' + user_line,
    ), encoding="utf-8")

    result = _run(config)

    assert result.returncode == 0, result.stderr
    migrated = config.read_text(encoding="utf-8")
    assert user_line in migrated, "operator edits survive the migration"
    assert EXPECTED_IMPORTS in migrated


def test_missing_config_is_a_no_op(tmp_path: Path) -> None:
    # tmpfiles has not seeded yet (kubeadm sysext not installed, or the
    # directory is on a read-only fuse snapshot the migrator cannot write).
    # containerd.service's prior ExecStartPre reseeds via tmpfiles; the
    # migrator must not race it or block startup.
    config = tmp_path / "absent.toml"

    result = _run(config)

    assert result.returncode == 0, result.stderr
    assert not config.exists()


def test_top_level_imports_when_config_has_no_section_header(tmp_path: Path) -> None:
    # Some pre-imports kubeadm configs (operator hand-rolls) reach the
    # migrator with only top-level scalars and no [section] table. The
    # migrator must still land `imports` at top level so containerd sees it.
    config = tmp_path / "config.toml"
    config.write_text('version = 3\nroot = "/var/lib/containerd"\n', encoding="utf-8")

    result = _run(config)

    assert result.returncode == 0, result.stderr
    parsed = tomllib.loads(config.read_text(encoding="utf-8"))
    assert parsed["imports"] == [
        "/usr/share/bluefin/containerd/conf.d/*.toml",
        "/etc/containerd/conf.d/*.toml",
    ]
    # Both branches share one printf block, so the blame comment reads the
    # same and carries no stray backslash from shell quoting.
    migrated = config.read_text(encoding="utf-8")
    assert "`imports` glob" in migrated
    assert "\\" not in migrated


def test_multi_line_top_level_array_is_not_split_by_the_insertion(tmp_path: Path) -> None:
    # A continuation line of a top-level multi-line array starts with `[`
    # too, and the last element of an array of arrays carries no trailing
    # comma, so it ends in `]` exactly like a table header. If the migrator
    # treated either as a `[section]` header it would drop the imports block
    # inside the array and containerd would refuse to start on that node.
    config = tmp_path / "config.toml"
    config.write_text(
        'version = 3\n'
        'required_plugins = [\n'
        '  ["io.containerd.grpc.v1.cri"],\n'
        '  ["io.containerd.internal.v1.opt"]\n'
        ']\n'
        '\n'
        '[grpc]\n'
        '  address = "/run/containerd/containerd.sock"\n',
        encoding="utf-8",
    )

    result = _run(config)

    assert result.returncode == 0, result.stderr
    migrated = config.read_text(encoding="utf-8")
    parsed = tomllib.loads(migrated)
    assert parsed["imports"] == [
        "/usr/share/bluefin/containerd/conf.d/*.toml",
        "/etc/containerd/conf.d/*.toml",
    ]
    assert parsed["required_plugins"] == [
        ["io.containerd.grpc.v1.cri"],
        ["io.containerd.internal.v1.opt"],
    ]
    # The block lands at the top of the file, ahead of the array and of the
    # first table header — never between the array's elements.
    assert migrated.index(EXPECTED_IMPORTS) < migrated.index("required_plugins")
    assert migrated.index(EXPECTED_IMPORTS) < migrated.index("[grpc]")


def test_imports_written_after_a_table_header_is_nested_and_still_migrated(
    tmp_path: Path,
) -> None:
    # An `imports = [...]` appended to the end of the seeded config lands
    # inside the last table ([plugins."io.containerd.cri.v1.runtime".cni]),
    # where containerd never consults it — exactly the broken shape #351 is
    # about. The migrator must not read it as "already migrated": it has to
    # add a real top-level `imports` (the nested key stays where the
    # operator put it, and the result is valid TOML because the two keys
    # live in different tables).
    config = tmp_path / "config.toml"
    nested_line = 'imports = ["/etc/containerd/conf.d/*.toml"]'
    config.write_text(
        _seeded_kubeadm_config() + "\n# custom drops\n" + nested_line + "\n",
        encoding="utf-8",
    )

    result = _run(config)

    assert result.returncode == 0, result.stderr
    migrated = config.read_text(encoding="utf-8")
    parsed = tomllib.loads(migrated)
    assert parsed["imports"] == [
        "/usr/share/bluefin/containerd/conf.d/*.toml",
        "/etc/containerd/conf.d/*.toml",
    ]
    # The operator's nested line survives verbatim where they wrote it.
    assert nested_line in migrated
    assert parsed["plugins"]["io.containerd.cri.v1.runtime"]["cni"]["imports"] == [
        "/etc/containerd/conf.d/*.toml",
    ]


def test_a_commented_out_imports_line_does_not_count_as_migrated(tmp_path: Path) -> None:
    # A commented `# imports = [...]` is inert: containerd never sees it, so
    # the migrator must still write a live top-level line, and exactly one.
    config = tmp_path / "config.toml"
    config.write_text(
        '# imports = ["/etc/containerd/conf.d/*.toml"]\n' + _seeded_kubeadm_config(),
        encoding="utf-8",
    )

    result = _run(config)

    assert result.returncode == 0, result.stderr
    migrated = config.read_text(encoding="utf-8")
    parsed = tomllib.loads(migrated)
    assert parsed["imports"] == [
        "/usr/share/bluefin/containerd/conf.d/*.toml",
        "/etc/containerd/conf.d/*.toml",
    ]
    live_imports = [
        line for line in migrated.splitlines()
        if re.match(r"^[ \t]*imports[ \t]*=", line)
    ]
    assert len(live_imports) == 1, migrated


@pytest.mark.parametrize("indent", ["  ", "\t"])
def test_an_indented_top_level_imports_is_already_migrated(tmp_path: Path, indent: str) -> None:
    # TOML ignores leading whitespace, so `  imports = [...]` ahead of any
    # table header is a top-level key containerd honours. Prepending a
    # second one would make the file unparseable ("Cannot overwrite a
    # value") and crash-loop containerd, which the service's `-` prefix
    # cannot prevent once the write succeeded.
    config = tmp_path / "config.toml"
    config.write_text(
        "version = 3\n" + indent + 'imports = ["/etc/containerd/conf.d/*.toml"]\n'
        '\n[grpc]\n  address = "/run/containerd/containerd.sock"\n',
        encoding="utf-8",
    )
    expected = config.read_text(encoding="utf-8")
    before = config.stat()

    result = _run(config)

    assert result.returncode == 0, result.stderr
    assert config.read_text(encoding="utf-8") == expected
    assert (config.stat().st_mtime_ns, config.stat().st_ino) == (before.st_mtime_ns, before.st_ino)


def test_content_that_does_not_parse_as_toml_is_never_installed(tmp_path: Path) -> None:
    # Defence in depth: whatever shape the on-disk config has, the migrator
    # must not write a file containerd cannot parse — a successful write of
    # a broken config crash-loops containerd, and the `-` prefix on the
    # ExecStartPre cannot undo that. Here the pre-existing config is already
    # invalid TOML (a duplicated key), so the composed content is too.
    config = tmp_path / "config.toml"
    broken = 'version = 3\nversion = 4\n'
    config.write_text(broken, encoding="utf-8")

    result = _run(config)

    assert result.returncode != 0
    assert config.read_text(encoding="utf-8") == broken, "the live config is untouched"
    assert "not valid TOML" in result.stderr
    # The candidate is kept and named so an operator can inspect it.
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f"{config.name}.new")]
    assert len(leftovers) == 1, leftovers
    assert str(leftovers[0]) in result.stderr


def test_unknown_argument_is_rejected(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(_seeded_kubeadm_config(), encoding="utf-8")

    result = subprocess.run(
        ["bash", str(HELPER), "--bogus"],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "unknown argument" in result.stderr
    # The config must not be touched on argument errors.
    assert config.read_text(encoding="utf-8") == _seeded_kubeadm_config()


def test_mode_owner_and_inode_survive(tmp_path: Path) -> None:
    # containerd.service installs /etc/containerd/config.toml at 0600; if the
    # migrator's `mv` over the existing file dropped it back to umask 0644
    # (or replaced a symlink with a regular file), operators who locked the
    # file down lose that on every containerd restart. Verify the file's
    # mode and inode are preserved across the migration.
    config = tmp_path / "config.toml"
    config.write_text(_seeded_kubeadm_config(), encoding="utf-8")
    config.chmod(0o600)
    before_inode = config.stat().st_ino
    before_mode = config.stat().st_mode & 0o777

    result = _run(config)

    assert result.returncode == 0, result.stderr
    assert config.stat().st_ino == before_inode
    assert (config.stat().st_mode & 0o777) == before_mode
    # No `${CONF}.new*` may be left behind on success (the suffix is `$$`).
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f"{config.name}.new")]
    assert leftovers == [], f"tmpfile leaked after success: {leftovers}"


def test_failed_write_keeps_the_complete_migrated_content(tmp_path: Path) -> None:
    # `cat > "${CONF}"` truncates before it writes, so a failure part-way
    # (ENOSPC, read-only or immutable config) could leave the node with a
    # truncated /etc/containerd/config.toml. The migrator must keep the tmp
    # file — the only complete copy — and name it on stderr, never delete it
    # and leave the operator with nothing to restore.
    config = tmp_path / "config.toml"
    config.write_text(_seeded_kubeadm_config(), encoding="utf-8")
    config.chmod(0o444)

    result = _run(config)

    assert result.returncode != 0, result.stdout
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(f"{config.name}.new")]
    assert len(leftovers) == 1, f"the complete content must survive: {leftovers}"
    kept = leftovers[0].read_text(encoding="utf-8")
    assert EXPECTED_IMPORTS in kept
    assert 'address = "/run/containerd/containerd.sock"' in kept
    assert str(leftovers[0]) in result.stderr, "the kept file is named in the log"
    # The read-only config itself is untouched (the redirect never opened it).
    assert config.read_text(encoding="utf-8") == _seeded_kubeadm_config()
