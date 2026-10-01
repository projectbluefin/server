"""Public SPDX fragment provenance, not upstream publisher signature verification."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("baseline_sbom", Path(__file__).parents[1] / "produce-baseline.py")
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


class PlatformSbomTests(unittest.TestCase):
    def fixture(self):
        digest = "sha256:" + "a" * 64
        lock = {"baseline_commit": "c" * 40,
                "sources": {"argocd": {"version": "3.5.3", "commit": "d" * 40,
                            "url": "https://raw.githubusercontent.com/argoproj/argo-cd/v3.5.3/manifests/core-install.yaml",
                            "sha256": "e" * 64},
                            "console": {"version": "0.3.42", "commit": "b" * 40}},
                "maintained_resources": {"dashboard/20-console.yaml.in": "f" * 64},
                "images": {"argocd": {"ref": "quay.io/argoproj/argocd:v3.5.3@" + digest, "digest": digest},
                           "console": {"ref": "ghcr.io/kubestellar/console:v0.3.42@" + digest, "digest": digest}}}
        return lock

    def fragment(self, lock):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            resource = directory / "manifests/dashboard/20-console.yaml"
            resource.parent.mkdir(parents=True)
            resource.write_bytes(b"resolved actual resource\n")
            (directory / "platform-lock.json").write_text("public lock\n")
            return baseline.platform_sbom(lock, directory)

    def test_fragment_preserves_exact_resource_and_stock_image_provenance(self):
        fragment = self.fragment(self.fixture())
        packages = fragment["packages"]
        ids = {package["SPDXID"] for package in packages}
        self.assertEqual(len(ids), len(packages))
        self.assertTrue(all(identifier.startswith("SPDXRef-Platform-") for identifier in ids))
        upstream = next(package for package in packages if package["name"] == "argocd upstream resource bundle")
        self.assertEqual(upstream["versionInfo"], "3.5.3")
        self.assertEqual(upstream["checksums"], [{"algorithm": "SHA256", "checksumValue": "e" * 64}])
        console = next(package for package in packages if package["name"] == "console upstream OCI image")
        self.assertEqual(console["downloadLocation"], self.fixture()["images"]["console"]["ref"])
        self.assertEqual(console["checksums"][0]["checksumValue"], "a" * 64)
        for relationship in fragment["relationships"]:
            self.assertIn(relationship["spdxElementId"], ids)
            self.assertIn(relationship["relatedSpdxElement"], ids)
        self.assertFalse(any(relationship["relationshipType"] == "GENERATED_FROM" and
                             relationship["spdxElementId"] == console["SPDXID"]
                             for relationship in fragment["relationships"]))
        self.assertTrue(any(relationship["relationshipType"] == "GENERATED_FROM" and
                            relationship["spdxElementId"].startswith("SPDXRef-Platform-ResolvedResource-")
                            for relationship in fragment["relationships"]))
        self.assertNotIn("/private/", str(fragment))
        self.assertTrue(all(package["licenseDeclared"] == "NOASSERTION" for package in packages))
        self.assertTrue(all("supplier" not in package and "signature" not in package for package in packages))

    def test_unknown_source_checksum_is_not_invented_and_inconsistent_image_is_rejected(self):
        lock = self.fixture()
        del lock["sources"]["argocd"]["sha256"]
        fragment = self.fragment(lock)
        source = next(package for package in fragment["packages"] if package["name"] == "argocd upstream source")
        self.assertNotIn("checksums", source)
        lock["images"]["argocd"]["digest"] = "sha256:" + "1" * 64
        with self.assertRaises(ValueError):
            self.fragment(lock)

    def test_modified_packaging_producer_invalidates_source_proof_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary)
            producer = source / "produce-baseline.py"
            producer.write_bytes(b"reviewed producer bytes")
            lock = {"schema": 1, "images": {}, "maintained_resources": {}, "producer_sha256": hashlib.sha256(producer.read_bytes()).hexdigest()}
            (source / "source-lock.json").write_text(json.dumps(lock))
            baseline.validate_source_lock(source)
            producer.write_bytes(b"different producer bytes")
            with self.assertRaises(ValueError):
                baseline.validate_source_lock(source)


if __name__ == "__main__":
    unittest.main()
