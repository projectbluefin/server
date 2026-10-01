#!/usr/bin/env python3
"""Host publication/stock provenance regressions; no downloads or cluster execution."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


prepare = load("prepare", "prepare-server.py")
verify = load("verify", "verify-server-platform.py")


class ImportSafetyTests(unittest.TestCase):
    def test_unmanaged_destination_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            destination = base / "amd64"
            destination.mkdir()
            (destination / "owner-file").write_text("keep")
            generation = base / ".generations" / "new"
            generation.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "unowned"):
                prepare.publish(generation, destination)
            self.assertEqual((destination / "owner-file").read_text(), "keep")

    def test_external_symlink_cannot_be_adopted_even_with_owner_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            outside = base / "outside"
            outside.mkdir()
            prepare.seal(outside, "old")
            parent = base / "imports"
            parent.mkdir()
            destination = parent / "amd64"
            destination.symlink_to(outside, target_is_directory=True)
            generation = parent / ".generations" / "new"
            generation.mkdir(parents=True)
            with self.assertRaisesRegex(ValueError, "unowned"):
                prepare.publish(generation, destination)
            self.assertTrue(outside.exists())

    def test_published_source_is_real_directory_and_prior_bytes_remain_retained(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old, new = [base / ".generations" / name for name in ("old", "new")]
            for directory, payload in [(old, "old bytes"), (new, "new bytes")]:
                directory.mkdir(parents=True)
                (directory / "payload").write_text(payload)
                prepare.seal(directory, payload)
            destination = base / "amd64"
            prepare.publish(old, destination)
            self.assertTrue(destination.is_dir())
            self.assertFalse(destination.is_symlink())
            opened_prior = (destination / "payload").open()
            try:
                prepare.publish(new, destination)
                self.assertEqual((destination / "payload").read_text(), "new bytes")
                self.assertEqual(opened_prior.read(), "old bytes")
            finally:
                opened_prior.close()
            self.assertFalse(destination.is_symlink())
            self.assertTrue(prepare.owned_generation(destination))
            self.assertTrue(prepare.reusable(destination, "new bytes"))
            self.assertEqual((new / "payload").read_text(), "old bytes")
            self.assertTrue(prepare.reusable(new, "old bytes"))

    def test_modified_generation_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "payload").write_text("actual")
            prepare.seal(directory, "inputs")
            self.assertTrue(prepare.reusable(directory, "inputs"))
            self.assertFalse(prepare.reusable(directory, "different stock source"))
            (directory / "payload").write_text("modified")
            self.assertFalse(prepare.reusable(directory, "inputs"))

    def test_unsealed_candidate_cannot_interrupt_existing_real_import(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old, unfinished = [base / ".generations" / name for name in ("old", "unfinished")]
            old.mkdir(parents=True)
            unfinished.mkdir()
            (old / "payload").write_text("complete bytes")
            prepare.seal(old, "old")
            destination = base / "amd64"
            prepare.publish(old, destination)
            (unfinished / "payload").write_text("partial")
            with self.assertRaisesRegex(ValueError, "unsealed"):
                prepare.publish(unfinished, destination)
            self.assertEqual((destination / "payload").read_text(), "complete bytes")
            self.assertFalse(destination.is_symlink())


class EvidenceTests(unittest.TestCase):
    def test_actual_stock_cli_output_and_proof_identity_reject_changed_artifacts(self):
        producer = prepare.REPO / "files/server/manifests/produce-baseline.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root / "platform"
            revision = subprocess.check_output([sys.executable, str(producer), "--output", str(staged)], text=True).strip()
            identity = verify.proof_identity(staged)
            self.assertEqual(identity["baseline_commit"], revision)
            for relative in ("baseline-commit", "platform-lock.json", "sbom-packages.json", "manifests/dashboard/20-console.yaml"):
                target = staged / relative
                original = target.read_bytes()
                target.write_bytes(original + b"\nchanged consumer artifact\n")
                try:
                    with self.subTest(artifact=relative), self.assertRaises(ValueError):
                        verify.proof_identity(staged)
                finally:
                    target.write_bytes(original)
            bare = staged / "baseline.git"
            tree = subprocess.check_output(["git", "--git-dir", str(bare), "rev-parse", "HEAD^{tree}"], text=True).strip()
            environment = dict(verify.os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL="/dev/null",
                               GIT_AUTHOR_NAME="Boundary test", GIT_AUTHOR_EMAIL="test@example.invalid",
                               GIT_COMMITTER_NAME="Boundary test", GIT_COMMITTER_EMAIL="test@example.invalid")
            other_commit = subprocess.check_output(["git", "--git-dir", str(bare), "commit-tree", tree],
                                                  input="Different baseline identity\n", text=True, env=environment).strip()
            subprocess.run(["git", "--git-dir", str(bare), "update-ref", "refs/heads/baseline", other_commit], check=True)
            with self.assertRaisesRegex(ValueError, "HEAD"):
                verify.proof_identity(staged)
            subprocess.run(["git", "--git-dir", str(bare), "update-ref", "refs/heads/baseline", revision], check=True)
            self.assertEqual(verify.proof_identity(staged), identity)

    def test_pod_health_alone_or_wrong_revision_is_not_reconciliation(self):
        app = {"status": {"health": {"status": "Healthy"},
                          "sync": {"status": "Synced", "revision": "old"},
                          "operationState": {"phase": "Succeeded"},
                          "resources": [{"kind": "Deployment", "name": "argocd-valkey"}]}}
        self.assertFalse(verify.reconciled(app, "new"))
        app["status"]["sync"]["revision"] = "new"
        self.assertTrue(verify.reconciled(app, "new"))
        app["status"]["conditions"] = [{"type": "ComparisonError", "message": "cannot clone"}]
        self.assertFalse(verify.reconciled(app, "new"))

    def test_stale_source_or_boolean_only_proof_is_not_reused(self):
        identity = {"baseline_commit": "a" * 40, "source_lock_sha256": "c" * 64,
                    "platform_lock_sha256": "d" * 64, "architecture": "amd64",
                    "images": json.loads((prepare.REPO / "files/server/manifests/source-lock.json").read_text())["images"]}
        proof = {"schema": 1, "identity": identity, "argocd": "3.5.3", "valkey": "9.1.2",
                 **{case: True for case in verify.CASES}}
        self.assertFalse(verify.matching_proof(proof, identity))
        with tempfile.TemporaryDirectory() as temporary:
            artifacts = Path(temporary)
            proof["artifacts"] = str(artifacts)
            proof["observations"] = {}
            proof["scope"] = {"selected_actual_core_only": True,
                              "production_roles_used": ["argocd/20-rbac.yaml", "argocd/21-cache-rbac.yaml", "bootstrap-rbac.yaml"],
                              "additional_test_rbac": [],
                              "not_verified": ["full-platform-sync", "Cilium-network-policy-enforcement", "Console-identity", "workload-admission"]}
            for case in verify.CASES:
                application = {"metadata": {"uid": "observed-uid"}, "status": {
                    "sync": {"status": "Synced", "revision": identity["baseline_commit"]},
                    "operationState": {"phase": "Succeeded"},
                    "resources": [{"kind": "Deployment", "name": "argocd-valkey"}]}}
                evidence = artifacts / (case + ".json")
                evidence.write_bytes(verify.canonical({"case": case, "identity": identity,
                                                       "application": application}))
                proof["observations"][case] = {"revision": identity["baseline_commit"],
                    "application_uid": "observed-uid", "evidence_sha256": verify.sha256(evidence)}
            self.assertTrue(verify.matching_proof(proof, identity))
            self.assertFalse(verify.matching_proof(proof, dict(identity, source_lock_sha256="e" * 64)))
            for field, value in (("platform_lock_sha256", "0" * 64), ("architecture", "arm64")):
                with self.subTest(field=field):
                    self.assertFalse(verify.matching_proof(proof, dict(identity, **{field: value})))
            changed_images = copy.deepcopy(identity["images"])
            changed_images["console"]["ref"] = "ghcr.io/kubestellar/console:v0.3.42@" + changed_images["console"]["configs"]["amd64"]["manifest_digest"]
            self.assertFalse(verify.matching_proof(proof, dict(identity, images=changed_images)))
            (artifacts / "offline_snapshot.json").write_text("tampered")
            self.assertFalse(verify.matching_proof(proof, identity))
            for malformed in (None, [], dict(proof, observations=None)):
                self.assertFalse(verify.matching_proof(malformed, identity))

    def test_private_or_symlinked_public_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "config").write_text("public")
            (directory / "secret-link").symlink_to("/etc/shadow")
            with self.assertRaisesRegex(ValueError, "symlink"):
                verify.validate_public_snapshot(directory)


if __name__ == "__main__":
    unittest.main()
