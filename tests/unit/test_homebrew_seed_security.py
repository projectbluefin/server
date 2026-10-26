"""Exercise prefix seeding's ownership boundary with a real unprivileged process."""
import importlib.machinery
import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pytest

SOURCE = Path(__file__).resolve().parents[2] / "files/homebrew/bluefin-homebrew-prepare"
loader = importlib.machinery.SourceFileLoader("homebrew_seed_prepare", str(SOURCE))
spec = importlib.util.spec_from_loader(loader.name, loader)
prepare = importlib.util.module_from_spec(spec)
loader.exec_module(prepare)


class SeedSecurityTests(unittest.TestCase):
    # skipUnless keeps `python3 -m unittest` usable; under pytest the root
    # marker decides first (tests/unit/conftest.py).
    @pytest.mark.root
    @unittest.skipUnless(os.geteuid() == 0, "requires real ownership changes")
    def test_owner_cannot_replace_directories_during_privileged_seeding(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            seed = root / "seed"
            (seed / "lib").mkdir(parents=True)
            (seed / "lib/package").write_text("seed-package")
            state = root / "state"
            state.mkdir()
            victim = root / "victim"
            victim.mkdir()
            (victim / "package").write_text("protected-host-file")
            walk = os.walk
            attempts = []

            def racing_walk(top, **kwargs):
                for path, directories, files in walk(top, **kwargs):
                    if Path(path).name == "lib":
                        # Pause at a real traversal boundary; do not mock chown,
                        # permissions, links or the attacking process's identity.
                        result = subprocess.run(
                            ["/usr/bin/python3", "-I", "-c",
                             "import os,sys\n"
                             "try:\n"
                             " os.rename(sys.argv[1], sys.argv[1]+'.original')\n"
                             " os.symlink(sys.argv[2], sys.argv[1])\n"
                             "except PermissionError:\n"
                             " sys.exit(13)\n",
                             path, str(victim)],
                            user=65534, group=65534, extra_groups=[],
                            cwd=root, capture_output=True, check=False)
                        attempts.append(result.returncode)
                    yield path, directories, files

            with patch.object(prepare.os, "walk", racing_walk):
                prepare.seed_prefix(seed, state / "prefix", 65534, 65534)

            self.assertEqual(victim.stat().st_uid, 0,
                             "seeding must never chown an attacker-selected host directory")
            self.assertEqual((victim / "package").stat().st_uid, 0)
            self.assertEqual(attempts, [13], "the owner must not access the unpublished copy")
            self.assertEqual((state / "prefix/lib/package").read_text(), "seed-package")
            self.assertEqual((state / "prefix/lib/package").stat().st_uid, 65534)


if __name__ == "__main__":
    unittest.main()
