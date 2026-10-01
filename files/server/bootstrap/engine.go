package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
)

type Engine struct {
	Root    string
	mu      sync.Mutex
	State   State
	Profile Profile
	busy    bool
}

func (e *Engine) path(p string) string { return filepath.Join(e.Root, p) }
func (e *Engine) persist() error {
	if err := saveJSON(e.path("/var/lib/bluefin/server/state.json"), &e.State); err != nil {
		return err
	}
	if err := os.MkdirAll(e.path("/run/issue.d"), 0755); err != nil {
		return err
	}
	text := fmt.Sprintf("Bluefin Server: %s (%s)\nPhysical lifecycle status and resume: tty1. Console is cluster-internal.\n", e.State.Phase, e.State.Role)
	return os.WriteFile(e.path("/run/issue.d/30-bluefin-server.issue"), []byte(text), 0644)
}
func command(input []byte, name string, args ...string) ([]byte, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, name, args...)
	if input != nil {
		cmd.Stdin = bytes.NewReader(input)
	}
	// Never attach process output to the journal: kubeadm can print enrollment credentials.
	out, err := cmd.Output()
	if err != nil {
		return nil, fmt.Errorf("%s_failed", filepath.Base(name))
	}
	return out, nil
}
func run(name string, args ...string) error { _, err := command(nil, name, args...); return err }
func kube(args ...string) ([]byte, error) {
	return command(nil, "kubectl", append([]string{"--kubeconfig=/etc/kubernetes/admin.conf"}, args...)...)
}
func (e *Engine) phase(p string) error {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.State.Phase = p
	e.State.Error = ""
	e.State.Revision++
	return e.persist()
}
func (e *Engine) fail(code string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	e.State.Phase = "failed"
	e.State.Error = code
	e.State.Revision++
	_ = e.persist()
}
func (e *Engine) load() error {
	profile, err := os.ReadFile(e.path("/etc/bluefin/server/profile"))
	if err != nil {
		return err
	}
	if strings.TrimSpace(string(profile)) != "complete" {
		return errors.New("profile_inert")
	}
	if err = loadJSON(e.path("/usr/share/bluefin-server/profile.json"), &e.Profile); err != nil {
		return err
	}
	if err = e.Profile.validate(); err != nil {
		return err
	}
	body, err := os.ReadFile(e.path("/var/lib/bluefin/server/state.json"))
	if errors.Is(err, os.ErrNotExist) {
		if err = e.requireUninitializedHost(); err != nil {
			return err
		}
		e.State = State{Schema: 1, Profile: "complete", Role: "unassigned", Phase: "pending", Revision: 1, Active: e.Profile.Runtime}
	} else if err == nil {
		// Ignore retired UI bookkeeping in rehearsal data, never its durable
		// cluster identity, role or runtime transaction.
		err = json.Unmarshal(body, &e.State)
	}
	if err != nil {
		return err
	}
	if e.State.Schema != 1 || e.State.Profile != "complete" || (e.State.Role != "unassigned" && e.State.Role != "worker" && e.State.Role != "controller") {
		return errors.New("invalid_durable_state")
	}
	if e.State.Role == "unassigned" {
		return e.selectInitialRole(time.Now())
	}
	if e.State.PendingWorkers != nil {
		e.State.WorkerUpgradeError = "automatic_worker_updates_unavailable"
	}
	return e.validateHostRole()
}
func verifyFile(path, digest string) error {
	if !hashPattern.MatchString(digest) {
		return errors.New("invalid_payload_digest")
	}
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	h := sha256.New()
	if _, err = io.Copy(h, f); err != nil {
		return err
	}
	if hex.EncodeToString(h.Sum(nil)) != digest {
		return errors.New("payload_digest_mismatch")
	}
	return nil
}
func (e *Engine) verifyRuntime(r Runtime) error {
	if !safeVersion.MatchString(r.ImageVersion) || filepath.Base(r.KubernetesFile) != r.KubernetesFile || filepath.Base(r.ContainerdFile) != r.ContainerdFile {
		return errors.New("invalid_runtime_paths")
	}
	base := e.path("/var/lib/bluefin/server/payloads/" + r.ImageVersion)
	if err := verifyFile(filepath.Join(base, r.KubernetesFile), r.KubernetesSHA256); err != nil {
		return err
	}
	return verifyFile(filepath.Join(base, r.ContainerdFile), r.ContainerdSHA256)
}
func atomicLink(target, path string) error {
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return err
	}
	temp := path + ".new"
	os.Remove(temp)
	if err := os.Symlink(target, temp); err != nil {
		return err
	}
	if err := os.Rename(temp, path); err != nil {
		return err
	}
	d, err := os.Open(filepath.Dir(path))
	if err != nil {
		return err
	}
	defer d.Close()
	return d.Sync()
}
func (e *Engine) selectRuntime(r Runtime) error {
	if err := e.protectReleases(&r); err != nil {
		return err
	}
	base := e.path("/var/lib/bluefin/server")
	generation := filepath.Join(base, "generations", r.ImageVersion)
	if err := os.MkdirAll(generation, 0700); err != nil {
		return err
	}
	payload := filepath.Join(base, "payloads", r.ImageVersion)
	if err := atomicLink(filepath.Join(payload, r.KubernetesFile), filepath.Join(generation, "kubernetes.raw")); err != nil {
		return err
	}
	if err := atomicLink(filepath.Join(payload, r.ContainerdFile), filepath.Join(generation, "containerd.raw")); err != nil {
		return err
	}
	// Stable sysext names both resolve through a single atomically replaced generation pointer.
	for _, name := range []string{"kubernetes", "containerd"} {
		if err := atomicLink(filepath.Join(base, "active-runtime", name+".raw"), e.path("/var/lib/extensions/"+name+".raw")); err != nil {
			return err
		}
	}
	return atomicLink(generation, filepath.Join(base, "active-runtime"))
}
func (e *Engine) prepareRuntime(r Runtime) error {
	for _, dir := range []string{"/etc/extensions", "/run/extensions", "/var/lib/extensions"} {
		entries, _ := os.ReadDir(e.path(dir))
		for _, entry := range entries {
			name := entry.Name()
			if strings.HasPrefix(name, "k0s") || strings.HasPrefix(name, "kubeadm") || (dir != "/var/lib/extensions" && (strings.HasPrefix(name, "kubernetes") || strings.HasPrefix(name, "containerd"))) {
				return errors.New("conflicting_runtime_extension")
			}
		}
	}
	if err := e.verifyRuntime(r); err != nil {
		return err
	}
	if err := e.selectRuntime(r); err != nil {
		return err
	}
	if err := run("systemd-sysext", "refresh"); err != nil {
		return err
	}
	if err := run("systemctl", "daemon-reload"); err != nil {
		return err
	}
	if err := run("systemd-tmpfiles", "--create", "bluefin-server-runtime.conf"); err != nil {
		return err
	}
	for _, p := range []string{"containerd/config.toml", "crictl.yaml"} {
		dst := e.path("/etc/" + p)
		if _, err := os.Stat(dst); errors.Is(err, os.ErrNotExist) {
			b, err := os.ReadFile(e.path("/usr/share/bluefin-server/runtime/" + p))
			if err != nil {
				return err
			}
			if err = os.MkdirAll(filepath.Dir(dst), 0755); err != nil {
				return err
			}
			if err = os.WriteFile(dst, b, 0600); err != nil {
				return err
			}
		}
	}
	if err := run("/usr/lib/systemd/systemd-modules-load"); err != nil {
		return err
	}
	if err := run("/usr/lib/systemd/systemd-sysctl"); err != nil {
		return err
	}
	if err := run("systemctl", "restart", "containerd.service"); err != nil {
		return err
	}
	out, err := command(nil, "ctr", "plugins", "ls")
	if err != nil {
		return err
	}
	ready := false
	for _, line := range strings.Split(string(out), "\n") {
		fields := strings.Fields(line)
		if len(fields) >= 4 && fields[0] == "io.containerd.cri.v1" && fields[1] == "runtime" && fields[len(fields)-1] == "ok" {
			ready = true
		}
	}
	if !ready {
		return errors.New("cri_runtime_not_ready")
	}
	return run("systemctl", "restart", "kubelet.service")
}
func persistent(path string) error {
	var s syscall.Statfs_t
	if err := syscall.Statfs(path, &s); err != nil {
		return err
	}
	switch uint64(s.Type) {
	case 0x01021994, 0x858458f6, 0x794c7630, 0x73717368:
		return errors.New("nonpersistent_host_state")
	}
	if s.Flags&1 != 0 {
		return errors.New("readonly_host_state")
	}
	return nil
}
func nodeAddress() (string, error) {
	interfaces, err := net.Interfaces()
	if err != nil {
		return "", err
	}
	for _, in := range interfaces {
		if in.Flags&net.FlagUp == 0 || in.Flags&net.FlagLoopback != 0 {
			continue
		}
		a, _ := in.Addrs()
		for _, v := range a {
			ip, _, _ := net.ParseCIDR(v.String())
			if ip.To4() != nil && privateIP(ip) {
				return ip.String(), nil
			}
		}
	}
	return "", errors.New("no_private_node_address")
}
func (e *Engine) resume() {
	e.mu.Lock()
	if e.busy || e.State.Role == "unassigned" {
		e.mu.Unlock()
		return
	}
	e.busy = true
	role := e.State.Role
	upgrade := e.State.Upgrade
	e.mu.Unlock()
	defer func() { e.mu.Lock(); e.busy = false; e.mu.Unlock() }()
	var err error
	if upgrade == nil {
		if err = cleanupUpgrade(); err != nil {
			e.fail("upgrade_hold_cleanup_failed")
			return
		}
	}
	if upgrade != nil {
		if err = e.resumeUpgradeRuntime(); err == nil {
			err = e.upgrade()
		}
	} else if role == "worker" {
		err = e.joinWorker()
	} else {
		err = e.initialize()
	}
	if err != nil {
		e.fail(err.Error())
	}
}
func objectUID(namespace, name string) (string, error) {
	b, err := kube("get", "namespace", name, "-o", "jsonpath={.metadata.uid}")
	if err != nil {
		return "", err
	}
	return strings.TrimSpace(string(b)), nil
}
func (e *Engine) clusterHealth() error {
	if err := run("kubectl", "--kubeconfig=/etc/kubernetes/admin.conf", "get", "--raw=/readyz"); err != nil {
		return err
	}
	hostname, err := os.Hostname()
	if err != nil {
		return err
	}
	_, err = kube("wait", "node/"+strings.ToLower(hostname), "--for=condition=Ready", "--timeout=300s")
	return err
}
func (e *Engine) initialize() error {
	if e.State.Role != "controller" {
		return errors.New("controller_role_required")
	}
	if err := e.validateHostRole(); err != nil {
		return err
	}
	if err := persistent("/etc"); err != nil {
		return err
	}
	if err := persistent("/var"); err != nil {
		return err
	}
	if err := e.phase("runtime"); err != nil {
		return err
	}
	if err := e.prepareRuntime(e.State.Active); err != nil {
		return err
	}
	if e.State.ClusterID == "" {
		path := "/etc/bluefin/server/kubeadm-init.yaml"
		if _, err := os.Stat(path); errors.Is(err, os.ErrNotExist) {
			for _, marker := range []string{"/etc/kubernetes/pki/ca.crt", "/etc/kubernetes/admin.conf", "/etc/kubernetes/manifests/kube-apiserver.yaml"} {
				if _, er := os.Stat(marker); er == nil {
					return errors.New("partial_init_configuration_missing")
				}
			}
			ip, err := nodeAddress()
			if err != nil {
				return err
			}
			host, _ := os.Hostname()
			cfg, err := kubeadmInitConfiguration(ip, strings.ToLower(host), e.State.Active.Kubernetes)
			if err != nil {
				return err
			}
			if err = os.MkdirAll("/etc/bluefin/server", 0700); err != nil {
				return err
			}
			if err = os.WriteFile(path, []byte(cfg), 0600); err != nil {
				return err
			}
		}
		if err := ensureProxyDisabled(path); err != nil {
			return err
		}
		if err := e.phase("kubeadm_init"); err != nil {
			return err
		}
		partial := false
		for _, marker := range []string{"/etc/kubernetes/pki/ca.crt", "/etc/kubernetes/admin.conf", "/etc/kubernetes/manifests/kube-apiserver.yaml"} {
			if _, err := os.Stat(marker); err == nil {
				partial = true
			}
		}
		if !partial {
			if err := run("kubeadm", "init", "--config="+path, "--skip-phases=addon/kube-proxy"); err != nil {
				return err
			}
		} else {
			// kubeadm cert/kubeconfig phases reuse existing keys. No init reset or etcd deletion.
			for _, phase := range [][]string{{"certs", "all"}, {"kubeconfig", "all"}, {"etcd", "local"}, {"control-plane", "all"}, {"kubelet-start"}, {"wait-control-plane"}, {"upload-config", "all"}, {"mark-control-plane"}, {"bootstrap-token"}, {"kubelet-finalize", "all"}, {"addon", "coredns"}} {
				args := append([]string{"init", "phase"}, phase...)
				args = append(args, "--config="+path)
				if err := run("kubeadm", args...); err != nil {
					return err
				}
			}
		}
	}
	if !e.State.Handoff && e.State.ClusterID != "" {
		path := "/etc/bluefin/server/kubeadm-init.yaml"
		if err := ensureProxyDisabled(path); err != nil {
			return err
		}
		if err := e.waitAPIReady(); err != nil {
			return err
		}
		if clusterID, err := objectUID("", "kube-system"); err != nil || clusterID != e.State.ClusterID {
			return errors.New("cluster_identity_changed")
		}
		if err := run("kubeadm", "init", "phase", "upload-config", "all", "--config="+path); err != nil {
			return err
		}
	}
	clusterID, err := objectUID("", "kube-system")
	if err != nil {
		return err
	}
	e.mu.Lock()
	if e.State.ClusterID != "" && e.State.ClusterID != clusterID {
		e.mu.Unlock()
		return errors.New("cluster_identity_changed")
	}
	e.State.ClusterID = clusterID
	err = e.persist()
	e.mu.Unlock()
	if err != nil {
		return err
	}
	if err = e.validateHostRole(); err != nil {
		return err
	}
	host, _ := os.Hostname()
	if !e.State.Handoff {
		if err = ensureSchedulableController(strings.ToLower(host)); err != nil {
			return err
		}
	}
	if _, err = kube("label", "node", strings.ToLower(host), "bluefin.io/controller=true", "--overwrite"); err != nil {
		return err
	}
	if err = e.reconcileControllerPlatform(); err != nil {
		return err
	}
	if err = e.clusterHealth(); err != nil {
		return err
	}
	return e.phase("ready")
}

func (e *Engine) reconcileControllerPlatform() error {
	if !e.State.Handoff || e.State.BaselineCommit != e.Profile.BaselineCommit {
		return e.platform()
	}
	return e.stockPlatformReady()
}
func (e *Engine) joinWorker() error {
	if e.State.Role != "worker" {
		return errors.New("worker_role_required")
	}
	if err := e.validateHostRole(); err != nil {
		return err
	}
	if err := e.phase("runtime"); err != nil {
		return err
	}
	if err := e.prepareRuntime(e.State.Active); err != nil {
		return err
	}
	if _, err := os.Stat("/etc/kubernetes/kubelet.conf"); errors.Is(err, os.ErrNotExist) {
		var join Join
		if err = loadJSON("/var/lib/bluefin/server/private-join.json", &join); err != nil {
			return errors.New("private_join_missing")
		}
		if err = join.validate(time.Now()); err != nil {
			return err
		}
		if join.ClusterID != e.State.ClusterID {
			return errors.New("cluster_identity_changed")
		}
		cfg := fmt.Sprintf("apiVersion: kubeadm.k8s.io/v1beta4\nkind: JoinConfiguration\ndiscovery:\n  bootstrapToken:\n    apiServerEndpoint: %s\n    token: %s\n    caCertHashes: [%s]\nnodeRegistration:\n  criSocket: unix:///run/containerd/containerd.sock\n", join.APIEndpoint, join.Token, join.CAHash)
		path := "/var/lib/bluefin/server/private-kubeadm-join.yaml"
		if err = os.WriteFile(path, []byte(cfg), 0600); err != nil {
			return err
		}
		if err = e.phase("kubeadm_join"); err != nil {
			return err
		}
		if err = e.executeJoin(join, path); err != nil {
			return err
		}
		os.Remove(path)
		os.Remove("/var/lib/bluefin/server/private-join.json")
	}
	// The persisted kubelet certificate, not an expired bootstrap token, is reboot authority.
	if err := run("systemctl", "is-active", "kubelet.service"); err != nil {
		return err
	}
	if err := run("kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "get", "--raw=/readyz"); err != nil {
		return err
	}
	host, _ := os.Hostname()
	if err := run("kubectl", "--kubeconfig=/etc/kubernetes/kubelet.conf", "wait", "node/"+strings.ToLower(host), "--for=condition=Ready", "--timeout=300s"); err != nil {
		return err
	}
	return e.phase("ready")
}
func (e *Engine) applyObject(v any) error {
	b, err := json.Marshal(v)
	if err != nil {
		return err
	}
	_, err = command(b, "kubectl", "--kubeconfig=/etc/kubernetes/admin.conf", "apply", "-f", "-")
	return err
}
