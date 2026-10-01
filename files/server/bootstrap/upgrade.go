package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

func (e *Engine) upgradeStage(stage string) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.State.Upgrade.Stage = stage
	e.State.Phase = "upgrading_" + stage
	e.State.Revision++
	return e.persist()
}
func (e *Engine) stageUpgrade(image string) error {
	if !safeVersion.MatchString(image) {
		return errors.New("invalid_image_version")
	}
	dir := e.path("/var/lib/bluefin/server/payloads/" + image)
	// Downloaded signed payload inventories use exactly the same staging consumer as first install.
	if err := run("/usr/libexec/bluefin-server-profile", "--stage="+image); err != nil {
		return err
	}
	var profile Profile
	if err := loadJSON(filepath.Join(dir, "profile.json"), &profile); err != nil {
		return err
	}
	if profile.Runtime.ImageVersion != image {
		return errors.New("target_profile_mismatch")
	}
	if err := profile.validate(); err != nil {
		return err
	}
	if err := e.verifyRuntime(profile.Runtime); err != nil {
		return err
	}
	if err := checkSkew(e.State.Active.Kubernetes, profile.Runtime.Kubernetes); err != nil {
		return err
	}
	if e.State.Role == "worker" {
		if err := e.workerUpgradeCheck(profile.Runtime); err != nil {
			return err
		}
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	e.State.Upgrade = &Transaction{Target: profile.Runtime, Stage: "staged", StartedAt: e.State.Upgrade.StartedAt}
	e.State.Phase = "upgrade_pending"
	e.State.Revision++
	return e.persist()
}
func (e *Engine) upgrade() error {
	tx := e.State.Upgrade
	if tx == nil {
		return errors.New("upgrade_transaction_missing")
	}
	if err := e.protectReleases(&tx.Target); err != nil {
		return err
	}
	if tx.Stage == "verify_payloads" {
		if err := e.stageUpgrade(tx.Target.ImageVersion); err != nil {
			return err
		}
		tx = e.State.Upgrade
	}
	if err := e.verifyRuntime(tx.Target); err != nil {
		return err
	}
	if err := checkSkew(e.State.Active.Kubernetes, tx.Target.Kubernetes); err != nil {
		return err
	}
	// A durable host hold survives both daemon and OS restarts. Do not replace an operator's hold.
	hold := "/etc/reboot-lock"
	const marker = "bluefin-server-runtime-upgrade\n"
	if _, err := os.Stat(hold); errors.Is(err, os.ErrNotExist) {
		if err = os.WriteFile(hold, []byte(marker), 0600); err != nil {
			return err
		}
	}
	if err := e.maintenancePod(); err != nil {
		return err
	}
	host, _ := os.Hostname()
	host = strings.ToLower(host)
	if e.State.Role == "controller" {
		if tx.Stage != "healthy" {
			if _, err := kube("cordon", host); err != nil {
				return err
			}
		}
	} else {
		if err := e.requireDrainedWorker(host); err != nil {
			return err
		}
	}
	if tx.Stage == "staged" {
		if e.State.Role == "controller" {
			if err := e.preflightFleet(tx.Target); err != nil {
				return err
			}
		}
		if e.State.Role == "controller" {
			dir := "/var/lib/etcd/bluefin-snapshots"
			if err := os.MkdirAll(dir, 0700); err != nil {
				return err
			}
			snapshot := fmt.Sprintf("%s/%d.db", dir, tx.StartedAt.Unix())
			if _, err := kube("exec", "-n", "kube-system", "etcd-"+host, "--", "etcdctl", "--endpoints=https://127.0.0.1:2379", "--cacert=/etc/kubernetes/pki/etcd/ca.crt", "--cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt", "--key=/etc/kubernetes/pki/etcd/healthcheck-client.key", "snapshot", "save", snapshot); err != nil {
				return err
			}
			if st, err := os.Stat(snapshot); err != nil || st.Size() < 4096 {
				return errors.New("etcd_snapshot_missing")
			}
			if err := os.Chmod(snapshot, 0600); err != nil {
				return err
			}
			f, err := os.Open(snapshot)
			if err != nil {
				return err
			}
			err = f.Sync()
			f.Close()
			if err != nil {
				return err
			}
			e.mu.Lock()
			e.State.Upgrade.Snapshot = snapshot
			err = e.persist()
			e.mu.Unlock()
			if err != nil {
				return err
			}
		}
		if err := e.upgradeStage("snapshot"); err != nil {
			return err
		}
	}
	if tx.Stage == "snapshot" {
		if e.State.Role == "controller" {
			if err := e.preflightFleet(tx.Target); err != nil {
				return err
			}
		}
		mount := "/run/bluefin-server/target-runtime"
		if err := os.MkdirAll(mount, 0700); err != nil {
			return err
		}
		raw := e.path("/var/lib/bluefin/server/payloads/" + tx.Target.ImageVersion + "/" + tx.Target.KubernetesFile)
		if err := run("systemd-dissect", "--mount", "--read-only", raw, mount); err != nil {
			return err
		}
		kubeadm := filepath.Join(mount, "usr/bin/kubeadm")
		var err error
		if e.State.Role == "controller" {
			err = run(kubeadm, "upgrade", "apply", tx.Target.Kubernetes, "--yes", "--certificate-renewal=true")
		} else {
			err = run(kubeadm, "upgrade", "node", "--kubeconfig=/etc/kubernetes/kubelet.conf")
		}
		unmountErr := run("umount", mount)
		if err != nil {
			return err
		}
		if unmountErr != nil {
			return unmountErr
		}
		if err = e.upgradeStage("control_plane"); err != nil {
			return err
		}
	}
	if tx.Stage == "control_plane" {
		if e.State.Role == "controller" {
			if _, err := kube("drain", host, "--ignore-daemonsets", "--delete-emptydir-data", "--pod-selector=bluefin.io/platform!=true", "--timeout=300s"); err != nil {
				return err
			}
		}
		if err := e.upgradeStage("runtime_switch"); err != nil {
			return err
		}
	}
	if tx.Stage == "runtime_switch" {
		if err := e.prepareRuntime(tx.Target); err != nil {
			return err
		}
		if err := e.upgradeStage("runtime"); err != nil {
			return err
		}
	}
	if tx.Stage == "runtime" {
		if e.State.Role == "controller" {
			if err := e.clusterHealth(); err != nil {
				return err
			}
			if _, err := kube("uncordon", host); err != nil {
				return err
			}
			if err := e.freshPod(); err != nil {
				return err
			}
		} else {
			if err := os.Remove("/etc/kubernetes/manifests/bluefin-maintenance.json"); err != nil {
				return err
			}
			if err := run("kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "wait", "pod/bluefin-maintenance-"+host, "-n", "bluefin-system", "--for=delete", "--timeout=120s"); err != nil {
				return err
			}
			if err := e.maintenancePod(); err != nil {
				return err
			}
			if err := run("kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "wait", "node/"+host, "--for=condition=Ready", "--timeout=300s"); err != nil {
				return err
			}
		}
		if e.State.Role == "controller" {
			if err := e.stockPlatformReady(); err != nil {
				return err
			}
		}
		if err := e.upgradeStage("healthy"); err != nil {
			return err
		}
	}
	if tx.Stage != "healthy" {
		return errors.New("invalid_upgrade_stage")
	}
	hasWorkers := false
	if e.State.Role == "controller" {
		nodes, err := registeredNodes()
		if err != nil {
			return err
		}
		for _, node := range nodes {
			if node.Name != host {
				hasWorkers = true
			}
		}
	}
	e.mu.Lock()
	if err := e.State.commitHealthyRuntime(hasWorkers); err != nil {
		e.mu.Unlock()
		return err
	}
	err := e.persist()
	e.mu.Unlock()
	if err != nil {
		return err
	}
	if err = e.protectReleases(nil); err != nil {
		return err
	}
	if err = cleanupUpgrade(); err != nil {
		return err
	}
	return nil
}
func (e *Engine) maintenancePod() error {
	host, _ := os.Hostname()
	pod := map[string]any{"apiVersion": "v1", "kind": "Pod", "metadata": map[string]any{"name": "bluefin-maintenance", "namespace": "bluefin-system", "labels": map[string]string{"bluefin.io/maintenance": "true"}}, "spec": map[string]any{"nodeName": strings.ToLower(host), "automountServiceAccountToken": false, "containers": []any{map[string]any{"name": "hold", "image": e.Profile.PauseImage, "securityContext": map[string]any{"runAsNonRoot": true, "runAsUser": 65532, "allowPrivilegeEscalation": false, "capabilities": map[string]any{"drop": []string{"ALL"}}}}}}}
	// A real kubelet static pod is mirrored by Kubernetes and safely skipped by drain.
	if err := saveJSON("/etc/kubernetes/manifests/bluefin-maintenance.json", pod); err != nil {
		return err
	}
	config := "/etc/kubernetes/admin.conf"
	if e.State.Role == "worker" {
		config = "/etc/kubernetes/kubelet.conf"
	}
	return run("kubectl", "--kubeconfig="+config, "wait", "pod/bluefin-maintenance-"+strings.ToLower(host), "-n", "bluefin-system", "--for=jsonpath={.status.phase}=Running", "--timeout=120s")
}
func (e *Engine) workerUpgradeCheck(target Runtime) error {
	out, err := command(nil, "kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "get", "--raw=/version")
	if err != nil {
		return err
	}
	var v struct {
		GitVersion string `json:"gitVersion"`
	}
	if err = json.Unmarshal(out, &v); err != nil {
		return err
	}
	api, err := version(v.GitVersion)
	if err != nil {
		return err
	}
	node, err := version(target.Kubernetes)
	if err != nil {
		return err
	}
	if node[0] != api[0] || node[1] > api[1] || node[1] < api[1]-1 {
		return errors.New("worker_upgrade_control_plane_skew")
	}
	return nil
}
func (e *Engine) requireDrainedWorker(host string) error {
	out, err := command(nil, "kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "get", "node", host, "-o", "json")
	if err != nil {
		return err
	}
	var node struct {
		Spec struct {
			Unschedulable bool `json:"unschedulable"`
		} `json:"spec"`
	}
	if err = json.Unmarshal(out, &node); err != nil {
		return err
	}
	if !node.Spec.Unschedulable {
		return errors.New("worker_must_be_drained_by_controller")
	}
	out, err = command(nil, "kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "get", "pods", "--all-namespaces", "--field-selector=spec.nodeName="+host, "-o", "json")
	if err != nil {
		return err
	}
	var pods struct {
		Items []DrainedPod `json:"items"`
	}
	if err = json.Unmarshal(out, &pods); err != nil {
		return err
	}
	return drainedPodsSafe(pods.Items)
}
func cleanupUpgrade() error {
	if err := os.Remove("/etc/kubernetes/manifests/bluefin-maintenance.json"); err != nil && !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if b, err := os.ReadFile("/etc/reboot-lock"); err == nil && string(b) == "bluefin-server-runtime-upgrade\n" {
		return os.Remove("/etc/reboot-lock")
	}
	return nil
}
