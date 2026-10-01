"""Behavioral checks for the signed packaging producer; run with unittest."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

PRODUCER = Path(__file__).parents[1] / "produce-baseline.py"
spec = importlib.util.spec_from_file_location("baseline", PRODUCER)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class SnapshotTests(unittest.TestCase):

    def test_snapshot_reopens_at_exact_revision_and_reproduces_commit(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            first, second = directory / "first.git", directory / "second.git"
            files = {"platform/a.yaml": b"apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: desired\n"}
            revision = baseline.snapshot(first, files)
            self.assertEqual(revision, baseline.snapshot(second, dict(reversed(list(files.items())))))
            self.assertEqual(subprocess.check_output(["git", "--git-dir", str(first), "show",
                                                     revision + ":platform/a.yaml"]), files["platform/a.yaml"])
            self.assertEqual(subprocess.check_output(["git", "--git-dir", str(first), "rev-parse", "HEAD"])
                             .decode().strip(), revision)

    def test_payload_changes_revision_and_unsafe_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            one = baseline.snapshot(directory / "one.git", {"platform/a.yaml": b"one"})
            two = baseline.snapshot(directory / "two.git", {"platform/a.yaml": b"two"})
            self.assertNotEqual(one, two)
            with self.assertRaises(ValueError):
                baseline.snapshot(directory / "unsafe.git", {"../private": b"bad"})

    def test_reconciliation_does_not_request_root_owned_quota_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "platform"
            revision = baseline.render(PRODUCER.parent, output)
            git = ["git", "--git-dir", str(output / "baseline.git")]
            names = subprocess.check_output(git + ["ls-tree", "-r", "--name-only", revision]).decode().splitlines()
            for name in names:
                if name.endswith("kustomization.yaml"):
                    continue
                payload = subprocess.check_output(git + ["show", revision + ":" + name])
                for resource in yaml.safe_load_all(payload):
                    if resource:
                        self.assertNotIn(resource["kind"], {"ResourceQuota", "LimitRange"}, name)



if __name__ == "__main__":
    unittest.main()
