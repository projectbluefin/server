"""Evidence-reuse rejection tests; synthetic records are not compatibility proof."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("stock_proof", Path(__file__).parents[4] / "scripts/verify-server-platform.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


class ProofBindingTests(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        artifacts = Path(temporary.name)
        identity = {"baseline_commit": "a" * 40, "source_lock_sha256": "b" * 64,
                    "platform_lock_sha256": "c" * 64, "images": {
                        "console": {"ref": "ghcr.io/kubestellar/console:v0.3.42@sha256:" + "d" * 64},
                        "argoexec": {"ref": "quay.io/argoproj/argoexec:v4.1.4@sha256:" + "e" * 64}}}
        record = {"schema": 1, "identity": identity, "argocd": "3.5.3", "valkey": "9.1.2",
                  "artifacts": str(artifacts), "observations": {},
                  "scope": {"selected_actual_core_only": True, "additional_test_rbac": [],
                            "production_roles_used": ["argocd/20-rbac.yaml", "argocd/21-cache-rbac.yaml", "bootstrap-rbac.yaml"],
                            "not_verified": ["full-platform-sync", "Cilium-network-policy-enforcement", "Console-identity", "workload-admission"]}}
        application = {"metadata": {"uid": "same-application"}, "status": {
            "sync": {"status": "Synced", "revision": identity["baseline_commit"]},
            "resources": [{"kind": "Deployment", "name": "argocd-applicationset-controller", "namespace": "argocd", "status": "Synced"}],
            "operationState": {"phase": "Succeeded", "syncResult": {"revision": identity["baseline_commit"]}}}}
        for case in verifier.CASES:
            evidence = artifacts / (case + ".json")
            evidence.write_bytes(verifier.canonical({"case": case, "identity": identity, "application": application}))
            record[case] = True
            record["observations"][case] = {"revision": identity["baseline_commit"], "application_uid": "same-application",
                                             "evidence_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}
        return identity, record

    def test_reuse_rejects_other_stock_refs_source_or_revision(self):
        identity, record = self.fixture()
        self.assertTrue(verifier.matching_proof(record, identity))
        for field in ("baseline_commit", "images", "source_lock_sha256", "platform_lock_sha256"):
            other = copy.deepcopy(record)
            other["identity"][field] = "different-artifact"
            self.assertFalse(verifier.matching_proof(other, identity))

    def test_success_flags_without_exact_evidence_are_rejected(self):
        identity, record = self.fixture()
        evidence = Path(record["artifacts"]) / "offline_snapshot.json"
        evidence.write_bytes(b"tampered")
        self.assertFalse(verifier.matching_proof(record, identity))
        identity, record = self.fixture()
        for case in verifier.CASES:
            incomplete = copy.deepcopy(record)
            incomplete[case] = False
            self.assertFalse(verifier.matching_proof(incomplete, identity))

    def test_broader_roles_or_replaced_application_cannot_mask_production_failures(self):
        identity, record = self.fixture()
        broader = copy.deepcopy(record)
        broader["scope"]["additional_test_rbac"] = ["cluster-admin"]
        self.assertFalse(verifier.matching_proof(broader, identity))
        case = "offline_snapshot"
        evidence = Path(record["artifacts"]) / (case + ".json")
        import json
        changed = json.loads(evidence.read_text())
        changed["application"]["metadata"]["uid"] = "replacement"
        evidence.write_bytes(verifier.canonical(changed))
        record["observations"][case].update(application_uid="replacement", evidence_sha256=verifier.sha256(evidence))
        self.assertFalse(verifier.matching_proof(record, identity))


if __name__ == "__main__":
    unittest.main()
