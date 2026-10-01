"""Exercise installed policies on a workstation-local disposable API server only.

Set BLUEFIN_PLATFORM_TEST_KUBECONFIG and BLUEFIN_PLATFORM_TEST_IMAGE after applying
resolved product manifests. These are server-side consumer requests, not YAML/source
assertions. No external/live-cluster kubeconfig is accepted.
"""
import json
import os
import subprocess
import unittest
from urllib.parse import urlparse

NORMAL = "system:serviceaccount:bluefin-system:bluefin-console"


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = os.environ.get("BLUEFIN_PLATFORM_TEST_KUBECONFIG")
        image = os.environ.get("BLUEFIN_PLATFORM_TEST_IMAGE")
        if not config or not image:
            raise unittest.SkipTest("requires explicitly configured disposable platform proof cluster")
        cls.command = ["kubectl", "--kubeconfig", config]
        view = json.loads(subprocess.check_output(cls.command + ["config", "view", "--raw", "-o", "json"]))
        if any(urlparse(c["cluster"]["server"]).hostname not in {"127.0.0.1", "::1", "localhost"}
               for c in view["clusters"]):
            raise RuntimeError("refusing a non-workstation-local Kubernetes API")
        if "@sha256:" not in image:
            raise RuntimeError("test image must be the real digest-pinned product input")
        cls.image = image

    def admitted(self, body, accepted):
        result = subprocess.run(self.command + ["--as", NORMAL, "create", "--dry-run=server", "-f", "-"],
                                input=json.dumps(body), capture_output=True, text=True)
        self.assertEqual(result.returncode == 0, accepted, result.stderr)
        if not accepted:
            self.assertTrue("denied" in result.stderr.lower() or "forbidden" in result.stderr.lower(), result.stderr)

    def pod(self):
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "bounded-consumer",
                "namespace": "bluefin-apps", "labels": {"bluefin.io/ownership": "top-level-user"}},
                "spec": {"serviceAccountName": "bluefin-app-workload", "automountServiceAccountToken": False,
                         "securityContext": {"runAsNonRoot": True, "runAsUser": 1001,
                                             "seccompProfile": {"type": "RuntimeDefault"}},
                         "containers": [{"name": "task", "image": self.image,
                                         "command": ["/bin/sh", "-c"], "args": ["printf actual-result"],
                                         "resources": {"requests": {"cpu": "10m", "memory": "32Mi"},
                                                       "limits": {"cpu": "100m", "memory": "128Mi"}},
                                         "securityContext": {"allowPrivilegeEscalation": False,
                                                             "runAsNonRoot": True,
                                                             "readOnlyRootFilesystem": True,
                                                             "capabilities": {"drop": ["ALL"]}}}]}}

    def test_bounded_user_pod_is_admitted_without_platform_authority(self):
        self.admitted(self.pod(), True)

    def test_direct_pod_cannot_forge_controller_child_identity(self):
        for key in ("bluefin.io/controller-id", "batch.kubernetes.io/controller-uid"):
            with self.subTest(label=key):
                forged = self.pod()
                forged["metadata"]["labels"][key] = "another-controller"
                self.admitted(forged, False)

    def test_privileged_and_host_storage_effects_are_denied(self):
        privileged = self.pod()
        privileged["spec"]["containers"][0]["securityContext"]["privileged"] = True
        privileged["spec"]["containers"][0]["securityContext"]["allowPrivilegeEscalation"] = True
        self.admitted(privileged, False)
        mounted = self.pod()
        mounted["spec"]["volumes"] = [{"name": "host", "hostPath": {"path": "/etc/kubernetes"}}]
        self.admitted(mounted, False)

    def test_user_cannot_select_executor_account_or_skip_reboot_drain(self):
        elevated = self.pod()
        elevated["spec"]["serviceAccountName"] = "bluefin-native-mcp"
        self.admitted(elevated, False)
        bypass = self.pod()
        bypass["metadata"]["labels"]["bluefin.io/platform"] = "true"
        self.admitted(bypass, False)

    def workflow(self):
        pod = self.pod()["spec"]
        return {"apiVersion": "argoproj.io/v1alpha1", "kind": "Workflow", "metadata": {
                "name": "bounded-computation", "namespace": "argo",
                "labels": {"bluefin.io/ownership": "top-level-user"}}, "spec": {
                    "entrypoint": "compute", "serviceAccountName": "bluefin-workflow",
                    "automountServiceAccountToken": True,
                    "securityContext": pod["securityContext"],
                    "activeDeadlineSeconds": 60, "parallelism": 1,
                    "templates": [{"name": "compute", "container": pod["containers"][0]}]}}

    def test_compute_can_return_bounded_scratch_output(self):
        workflow = self.workflow()
        workflow["spec"]["volumes"] = [{"name": "bluefin-scratch", "emptyDir": {"sizeLimit": "128Mi"}}]
        template = workflow["spec"]["templates"][0]
        template["container"]["volumeMounts"] = [{"name": "bluefin-scratch", "mountPath": "/workspace"}]
        template["outputs"] = {"parameters": [{"name": "result", "valueFrom": {"path": "/workspace/result"}}]}
        self.admitted(workflow, True)

    def test_compute_cannot_select_privileged_identity_or_mount_secrets(self):
        no_token = self.workflow()
        no_token["spec"]["automountServiceAccountToken"] = False
        self.admitted(no_token, False)
        elevated = self.workflow()
        elevated["spec"]["serviceAccountName"] = "workflow-controller"
        self.admitted(elevated, False)
        secret = self.workflow()
        secret["spec"]["volumes"] = [{"name": "credential", "secret": {"secretName": "private-credential"}}]
        self.admitted(secret, False)

    def test_mutable_references_and_destructive_identity_are_denied(self):
        mutable = self.workflow()
        mutable["spec"]["workflowTemplateRef"] = {"name": "user-replaceable"}
        self.admitted(mutable, False)
        destructive = self.workflow()
        destructive["spec"]["serviceAccountName"] = "workflow-controller"
        self.admitted(destructive, False)


if __name__ == "__main__":
    unittest.main()
