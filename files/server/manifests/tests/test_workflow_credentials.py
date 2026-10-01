"""Exercise stock Argo task output and bounded credentials on a local API only.

Stock argoexec does not provide executor-only credential or symlink confinement.
Main shares the task-result-only Pod identity. Requires the resolved platform and
BLUEFIN_PLATFORM_TEST_COMPUTE_IMAGE, an acquired digest-pinned shell image.
"""
import json
import os
import subprocess
import time
import unittest
import uuid

import test_admission as admission

WORKFLOW_IDENTITY = "system:serviceaccount:argo:bluefin-workflow"


class WorkflowCredentialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admission.AdmissionTests.setUpClass.__func__(cls)

    def workflow(self):
        return admission.AdmissionTests.workflow(self)

    def pod(self):
        return admission.AdmissionTests.pod(self)

    def test_task_identity_cannot_read_secrets_or_mutate_workloads(self):
        for namespace, resource, verb in (("argo", "secrets", "get"),
                                          ("bluefin-apps", "pods", "delete"),
                                          ("bluefin-apps", "deployments", "patch"),
                                          ("argo", "workflows", "create")):
            result = subprocess.run(self.command + ["--as", WORKFLOW_IDENTITY, "auth", "can-i", verb,
                                                    resource, "-n", namespace], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(result.stdout.strip(), "no")

    def test_real_stock_argo_has_bounded_token_and_publishes_expected_output(self):
        compute = os.environ.get("BLUEFIN_PLATFORM_TEST_COMPUTE_IMAGE")
        if not compute or "@sha256:" not in compute:
            self.skipTest("requires an acquired digest-pinned shell-capable compute image")
        workflow = self.workflow()
        name = "stock-result-" + uuid.uuid4().hex[:12]
        workflow["metadata"]["name"] = name
        workflow["spec"]["volumes"] = [{"name": "bluefin-scratch", "emptyDir": {"sizeLimit": "128Mi"}}]
        template = workflow["spec"]["templates"][0]
        template["container"].update(image=compute, command=["/bin/sh", "-ec"], args=[
            "test -s /var/run/secrets/kubernetes.io/serviceaccount/token; "
            "printf 'actual-stock-result' > /workspace/result"],
            volumeMounts=[{"name": "bluefin-scratch", "mountPath": "/workspace"}])
        template["outputs"] = {"parameters": [{"name": "result", "valueFrom": {"path": "/workspace/result"}}]}
        created = False
        try:
            result = subprocess.run(self.command + ["--as", admission.NORMAL, "create", "-f", "-"],
                                    input=json.dumps(workflow), capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            created = True
            deadline = time.monotonic() + 180
            actual = None
            while time.monotonic() < deadline:
                actual = json.loads(subprocess.check_output(self.command + ["get", "workflow", name, "-n", "argo", "-o", "json"]))
                if actual.get("status", {}).get("phase") in {"Succeeded", "Failed", "Error"}:
                    break
                time.sleep(2)
            self.assertEqual(actual.get("status", {}).get("phase"), "Succeeded", actual.get("status"))
            results = [parameter["value"] for node in actual["status"].get("nodes", {}).values()
                       for parameter in node.get("outputs", {}).get("parameters", []) if parameter["name"] == "result"]
            self.assertEqual(results, ["actual-stock-result"])
        finally:
            if created:
                subprocess.run(self.command + ["delete", "workflow", name, "-n", "argo", "--wait=true", "--timeout=30s"], check=True)


if __name__ == "__main__":
    unittest.main()
