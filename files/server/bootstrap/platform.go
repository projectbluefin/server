package main

import (
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
)

func randomSecret() (string, error) {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return base64.RawURLEncoding.EncodeToString(b), nil
}
func (e *Engine) platform() error {
	root := "/usr/share/bluefin-server/manifests"
	if err := e.phase("networking"); err != nil {
		return err
	}
	for _, name := range []string{"namespaces.yaml", "bootstrap-rbac.yaml"} {
		if _, err := kube("apply", "--server-side", "-f", filepath.Join(root, name)); err != nil {
			return err
		}
	}
	ip, err := apiAdvertiseAddress(e.path("/etc/bluefin/server/kubeadm-init.yaml"))
	if err != nil {
		return err
	}
	if err = e.applyObject(map[string]any{"apiVersion": "v1", "kind": "ConfigMap", "metadata": map[string]string{"name": "bluefin-api-endpoint", "namespace": "kube-system"}, "data": map[string]string{"host": ip, "port": "6443"}}); err != nil {
		return err
	}
	// Generated credentials are outside the immutable Git baseline and never pruned by it.
	if _, err = kube("get", "secret", "argocd-valkey", "-n", "argocd"); err != nil {
		secret, err := randomSecret()
		if err != nil {
			return err
		}
		if err = e.applyObject(map[string]any{"apiVersion": "v1", "kind": "Secret", "metadata": map[string]string{"name": "argocd-valkey", "namespace": "argocd"}, "stringData": map[string]string{"auth": secret}}); err != nil {
			return err
		}
	}
	if _, err = kube("get", "secret", "argocd-secret", "-n", "argocd"); err != nil {
		if err = e.applyObject(map[string]any{"apiVersion": "v1", "kind": "Secret", "metadata": map[string]string{"name": "argocd-secret", "namespace": "argocd"}, "type": "Opaque"}); err != nil {
			return err
		}
	}
	if _, err = kube("get", "secret", "bluefin-in-cluster", "-n", "argocd"); err != nil {
		if err = e.applyObject(map[string]any{"apiVersion": "v1", "kind": "Secret", "metadata": map[string]any{"name": "bluefin-in-cluster", "namespace": "argocd", "labels": map[string]string{"argocd.argoproj.io/secret-type": "cluster"}}, "stringData": map[string]string{"name": "in-cluster", "server": "https://kubernetes.default.svc", "namespaces": "kube-system,argocd,argo,bluefin-system,bluefin-apps", "clusterResources": "true", "config": "{}"}}); err != nil {
			return err
		}
	}
	if err = e.selectBaseline(); err != nil {
		return err
	}
	if err = applyPhase(root, "cilium"); err != nil {
		return err
	}
	for _, name := range []string{"daemonset/cilium", "deployment/cilium-operator"} {
		if _, err = kube("rollout", "status", name, "-n", "kube-system", "--timeout=600s"); err != nil {
			return err
		}
	}
	if err = e.clusterHealth(); err != nil {
		return err
	}
	if err = e.phase("platform"); err != nil {
		return err
	}
	for _, phase := range []string{"argocd", "workflows", "mcp", "reboot"} {
		if err = applyPhase(root, phase); err != nil {
			return err
		}
	}
	if _, err = kube("apply", "--server-side", "-f", filepath.Join(root, "admission.yaml")); err != nil {
		return err
	}
	for _, ref := range []struct{ ns, name string }{{"argocd", "statefulset/argocd-application-controller"}, {"argocd", "deployment/argocd-repo-server"}, {"argocd", "deployment/argocd-applicationset-controller"}, {"argocd", "deployment/argocd-valkey"}, {"argo", "deployment/workflow-controller"}} {
		if _, err = kube("rollout", "status", ref.name, "-n", ref.ns, "--timeout=600s"); err != nil {
			return err
		}
	}
	if err = e.verifyBaseline(e.path("/var/lib/bluefin/server/baselines/baseline.git"), e.Profile.BaselineCommit); err != nil {
		return err
	}
	// The bootstrap-only baseline Application is outside its own bare snapshot.
	if _, err = kube("apply", "--server-side", "-f", filepath.Join(root, "argocd/30-baseline.yaml")); err != nil {
		return err
	}
	if err = e.phase("dashboard"); err != nil {
		return err
	}
	if err = e.prepareConsoleData(); err != nil {
		return err
	}
	if err = e.ensureConsoleJWT(); err != nil {
		return err
	}
	if err = applyPhase(root, "dashboard"); err != nil {
		return err
	}
	// Console is now root-owned, not a Git-managed child; transfer its old fields.
	if _, err = kube("apply", "--server-side", "--force-conflicts", "-f", filepath.Join(root, "dashboard/20-console.yaml")); err != nil {
		return err
	}
	return e.finishPlatform()
}

func (e *Engine) finishPlatform() error {
	if err := e.stockPlatformReady(); err != nil {
		return err
	}
	if err := e.waitBaseline(); err != nil {
		return err
	}
	if err := e.freshPod(); err != nil {
		return err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	e.State.BaselineCommit = e.Profile.BaselineCommit
	e.State.Handoff = true
	e.State.Revision++
	return e.persist()
}
func applyPhase(root, phase string) error {
	// Apply CRDs separately before resources referencing them, including large server-side schemas.
	bytes, err := command(nil, "kubectl", "kustomize", filepath.Join(root, phase))
	if err != nil {
		return err
	}
	// Resource grouping is performed by kubectl's API discovery only after all CRDs are established.
	// Producers export each phase's CRDs as a separate directory, avoiding text/YAML heuristics here.
	crds := filepath.Join(root, phase, "crds")
	if st, err := os.Stat(crds); err == nil && st.IsDir() {
		if _, err = kube("apply", "--server-side", "-f", crds); err != nil {
			return err
		}
		if _, err = kube("wait", "--for=condition=Established", "--timeout=180s", "-f", crds); err != nil {
			return err
		}
	}
	_, err = command(bytes, "kubectl", "--kubeconfig=/etc/kubernetes/admin.conf", "apply", "--server-side", "-f", "-")
	if err != nil || phase != "workflows" {
		return err
	}
	// Bootstrap templates precede quota admission. Wait for every CRD counter
	// before handing the namespace to users; Established is not quota discovery.
	if _, err = kube("apply", "--server-side", "-f", filepath.Join(root, phase, "30-bounds.yaml")); err != nil {
		return err
	}
	for _, resource := range []string{"workflows", "workflowtemplates", "cronworkflows"} {
		condition := `--for=jsonpath={.status.used.count/` + resource + `\.argoproj\.io}`
		if _, err = kube("wait", "resourcequota/bluefin-workflows", "-n", "argo", condition, "--timeout=600s"); err != nil {
			return errors.New("workflow_quota_discovery_unready")
		}
	}
	return nil
}
func (e *Engine) waitBaseline() error {
	// kubectl wait JSONPath binds readiness to the immutable build-produced baseline revision.
	if _, err := kube("wait", "applications.argoproj.io/bluefin-platform", "-n", "argocd", "--for=jsonpath={.status.sync.status}=Synced", "--timeout=600s"); err != nil {
		return err
	}
	if _, err := kube("wait", "applications.argoproj.io/bluefin-platform", "-n", "argocd", "--for=jsonpath={.status.health.status}=Healthy", "--timeout=600s"); err != nil {
		return err
	}
	b, err := kube("get", "application", "bluefin-platform", "-n", "argocd", "-o", "jsonpath={.status.sync.revision}")
	if err != nil {
		return err
	}
	if strings.TrimSpace(string(b)) != e.Profile.BaselineCommit {
		return errors.New("baseline_revision_not_reconciled")
	}
	return nil
}
func (e *Engine) freshPod() error {
	host, _ := os.Hostname()
	name := "bluefin-runtime-health"
	// This is a real new CRI sandbox on the controller, not a pre-existing Ready pod.
	_, _ = kube("delete", "pod", name, "-n", "bluefin-system", "--ignore-not-found", "--wait=true", "--timeout=60s")
	pod := map[string]any{"apiVersion": "v1", "kind": "Pod", "metadata": map[string]string{"name": name, "namespace": "bluefin-system"}, "spec": map[string]any{"nodeName": strings.ToLower(host), "restartPolicy": "Never", "automountServiceAccountToken": false, "securityContext": map[string]any{"runAsNonRoot": true, "runAsUser": 65532, "seccompProfile": map[string]string{"type": "RuntimeDefault"}}, "containers": []any{map[string]any{"name": "proof", "image": e.Profile.HealthImage, "command": []string{"/bin/sh", "-c", "exit 0"}, "securityContext": map[string]any{"allowPrivilegeEscalation": false, "readOnlyRootFilesystem": true, "capabilities": map[string]any{"drop": []string{"ALL"}}}}}}}
	if err := e.applyObject(pod); err != nil {
		return err
	}
	if _, err := kube("wait", "pod/"+name, "-n", "bluefin-system", "--for=jsonpath={.status.phase}=Succeeded", "--timeout=300s"); err != nil {
		return err
	}
	_, err := kube("delete", "pod", name, "-n", "bluefin-system", "--wait=true")
	return err
}
func (e *Engine) selectBaseline() error {
	commit := e.Profile.BaselineCommit
	if len(commit) != 40 {
		return errors.New("invalid_baseline_commit")
	}
	for _, c := range commit {
		if !strings.ContainsRune("0123456789abcdef", c) {
			return errors.New("invalid_baseline_commit")
		}
	}
	base := e.path("/var/lib/bluefin/server/baselines")
	target := filepath.Join(base, commit+".git")
	if err := os.MkdirAll(base, 0755); err != nil {
		return err
	}
	if _, err := os.Stat(target); errors.Is(err, os.ErrNotExist) {
		temp := target + ".new"
		if err = os.RemoveAll(temp); err != nil {
			return err
		}
		if err = run("cp", "-a", e.path("/usr/share/bluefin-server/baseline.git"), temp); err != nil {
			return err
		}
		if err = e.verifyBaseline(temp, commit); err != nil {
			return err
		}
		if err = run("chmod", "-R", "a-w", temp); err != nil {
			return err
		}
		if err = run("sync", "-f", temp); err != nil {
			return err
		}
		if err = os.Rename(temp, target); err != nil {
			return err
		}
	} else if err != nil {
		return err
	} else if err = e.verifyBaseline(target, commit); err != nil {
		return err
	}
	return atomicLink(commit+".git", filepath.Join(base, "baseline.git"))
}

func (e *Engine) verifyBaseline(directory, expected string) error {
	// The signed sysext covers repository bytes; its producer uses this loose ref.
	head, err := os.ReadFile(filepath.Join(directory, "HEAD"))
	if err != nil {
		return err
	}
	if strings.TrimSpace(string(head)) != "ref: refs/heads/baseline" {
		return errors.New("baseline_head_invalid")
	}
	revision, err := os.ReadFile(filepath.Join(directory, "refs/heads/baseline"))
	if err != nil {
		return err
	}
	if strings.TrimSpace(string(revision)) != expected {
		return errors.New("baseline_commit_mismatch")
	}
	return verifyBaselineContents(directory, e.path("/usr/share/bluefin-server/baseline-integrity.json"), expected)
}

func (e *Engine) prepareConsoleData() error {
	for _, directory := range []struct {
		path string
		uid  int
		mode os.FileMode
	}{
		{"/var/lib/bluefin/server/console", 0, 0711},
		{"/var/lib/bluefin/server/console/data", 1001, 0700},
		{"/var/lib/bluefin/server/console/.kc", 1001, 0700},
	} {
		path := e.path(directory.path)
		if err := os.MkdirAll(path, 0700); err != nil {
			return err
		}
		info, err := os.Lstat(path)
		if err != nil || !info.IsDir() || info.Mode().Perm()&0022 != 0 {
			return errors.New("unsafe_console_data_directory")
		}
		// The parent is root-owned; only the stock container's subPath data
		// directories belong to its numeric UID. No host account is created.
		if err = os.Lchown(path, directory.uid, directory.uid); err != nil {
			return err
		}
		if err = os.Chmod(path, directory.mode); err != nil {
			return err
		}
	}
	return nil
}

func (e *Engine) ensureConsoleJWT() error {
	out, err := kube("get", "secret", "bluefin-console-jwt", "-n", "bluefin-system", "--ignore-not-found", "-o", "json")
	if err != nil {
		return err
	}
	if len(strings.TrimSpace(string(out))) != 0 {
		var secret struct {
			Data map[string][]byte `json:"data"`
		}
		if err = json.Unmarshal(out, &secret); err != nil || len(secret.Data["jwt-secret"]) < 32 {
			return errors.New("console_jwt_secret_invalid")
		}
		return nil
	}
	value, err := randomSecret()
	if err != nil {
		return err
	}
	body, err := json.Marshal(map[string]any{"apiVersion": "v1", "kind": "Secret", "metadata": map[string]string{"name": "bluefin-console-jwt", "namespace": "bluefin-system"}, "type": "Opaque", "stringData": map[string]string{"jwt-secret": value}})
	if err != nil {
		return err
	}
	// Create, never apply: a transient read failure or another creator cannot
	// silently rotate the installation's persistent signing identity.
	_, err = command(body, "kubectl", "--kubeconfig=/etc/kubernetes/admin.conf", "create", "-f", "-")
	return err
}

func (e *Engine) configureConsole() error {
	body, err := kube("get", "secret", "bluefin-console-oauth", "-n", "bluefin-system", "--ignore-not-found", "-o", "json")
	if err != nil {
		return err
	}
	deployment, err := kube("get", "deployment", "bluefin-console", "-n", "bluefin-system", "--ignore-not-found", "-o", "json")
	if err != nil {
		return err
	}
	replicas, status := "0", "awaiting_oauth"
	if validateConsoleOAuth(body) == nil {
		status = "unavailable"
		if len(deployment) != 0 && e.validateStockDeployment("bluefin-console", deployment) == nil {
			replicas, status = "1", "configured"
		}
	}
	if len(deployment) != 0 {
		if _, err = kube("scale", "deployment/bluefin-console", "-n", "bluefin-system", "--replicas="+replicas); err != nil {
			return err
		}
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.State.ConsoleStatus == status {
		return nil
	}
	e.State.ConsoleStatus = status
	e.State.Revision++
	return e.persist()
}

func validateConsoleOAuth(body []byte) error {
	if len(strings.TrimSpace(string(body))) == 0 {
		return errors.New("console_oauth_unconfigured")
	}
	var secret struct {
		Data map[string][]byte `json:"data"`
	}
	if err := json.Unmarshal(body, &secret); err != nil {
		return errors.New("console_oauth_invalid")
	}
	for _, key := range []string{"client-id", "client-secret", "frontend-url", "allowed-logins", "admin-logins"} {
		if len(strings.TrimSpace(string(secret.Data[key]))) == 0 {
			return errors.New("console_oauth_unconfigured")
		}
	}
	return nil
}

func (e *Engine) stockPlatformReady() error {
	for _, ref := range []struct{ namespace, name string }{
		{"argocd", "statefulset/argocd-application-controller"},
		{"argocd", "deployment/argocd-repo-server"},
		{"argocd", "deployment/argocd-applicationset-controller"},
		{"argocd", "deployment/argocd-valkey"},
		{"argo", "deployment/workflow-controller"},
		{"bluefin-system", "deployment/bluefin-native-mcp"},
	} {
		if _, err := kube("rollout", "status", ref.name, "-n", ref.namespace, "--timeout=600s"); err != nil {
			return err
		}
	}
	out, err := kube("get", "deployment", "workflow-controller", "-n", "argo", "-o", "json")
	if err != nil {
		return err
	}
	if err = e.validateStockDeployment("workflow-controller", out); err != nil {
		return err
	}
	return e.configureConsole()
}

func (e *Engine) validateStockDeployment(name string, body []byte) error {
	var deployment struct {
		Spec struct {
			Template struct {
				Spec struct {
					Containers []struct {
						Name  string   `json:"name"`
						Image string   `json:"image"`
						Args  []string `json:"args"`
					} `json:"containers"`
				} `json:"spec"`
			} `json:"template"`
		} `json:"spec"`
	}
	if err := json.Unmarshal(body, &deployment); err != nil {
		return errors.New("stock_deployment_invalid")
	}
	for _, container := range deployment.Spec.Template.Spec.Containers {
		if name == "bluefin-console" && container.Name == "console" && container.Image == e.Profile.ConsoleImage {
			return nil
		}
		if name == "workflow-controller" && container.Name == "workflow-controller" {
			for _, arg := range container.Args {
				if arg == "--executor-image="+e.Profile.WorkflowExecutorImage {
					return nil
				}
			}
		}
	}
	return errors.New("stock_deployment_image_mismatch")
}
