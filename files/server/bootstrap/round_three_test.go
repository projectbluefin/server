package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestCNIEndpointUsesPersistedAdvertiseAddressNotInterfaceScan(t *testing.T) {
	path := filepath.Join(t.TempDir(), "kubeadm-init.yaml")
	body, err := kubeadmInitConfiguration("192.168.40.7", "controller", "1.36.5")
	if err != nil {
		t.Fatal(err)
	}
	if err = os.WriteFile(path, body, 0600); err != nil {
		t.Fatal(err)
	}
	address, err := apiAdvertiseAddress(path)
	if err != nil || address != "192.168.40.7" {
		t.Fatalf("published API host is not the control-plane address: %q %v", address, err)
	}
	legacy := "apiVersion: kubeadm.k8s.io/v1beta4\nkind: InitConfiguration\nlocalAPIEndpoint:\n  advertiseAddress: 10.10.0.3\n  bindPort: 6443\n"
	if err = os.WriteFile(path, []byte(legacy+"\n---\napiVersion: kubeadm.k8s.io/v1beta4\nkind: ClusterConfiguration\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if address, err = apiAdvertiseAddress(path); err != nil || address != "10.10.0.3" {
		t.Fatalf("existing installation lost its API address: %q %v", address, err)
	}
	for _, unusable := range []string{"169.254.11.9", "127.0.0.1", "", "not-an-address"} {
		rejected, err := kubeadmInitConfiguration(unusable, "controller", "1.36.5")
		if err != nil {
			t.Fatal(err)
		}
		if err = os.WriteFile(path, rejected, 0600); err != nil {
			t.Fatal(err)
		}
		if _, err = apiAdvertiseAddress(path); err == nil {
			t.Fatalf("CNI would be pointed at %q as the API server", unusable)
		}
	}
	if _, err = apiAdvertiseAddress(filepath.Join(t.TempDir(), "absent.yaml")); err == nil {
		t.Fatal("accepted a missing control-plane configuration")
	}
}

func fakeRuntimeHost(t *testing.T, criOK bool) *Engine {
	t.Helper()
	e := &Engine{Root: t.TempDir()}
	base := e.path("/var/lib/bluefin/server")
	generation := filepath.Join(base, "generations", "v1")
	for _, dir := range []string{generation, e.path("/var/lib/extensions"), e.path("/etc/containerd")} {
		if err := os.MkdirAll(dir, 0755); err != nil {
			t.Fatal(err)
		}
	}
	for _, name := range []string{"kubernetes", "containerd"} {
		if err := os.WriteFile(filepath.Join(generation, name+".raw"), []byte("payload"), 0600); err != nil {
			t.Fatal(err)
		}
		if err := atomicLink(filepath.Join(base, "active-runtime", name+".raw"), e.path("/var/lib/extensions/"+name+".raw")); err != nil {
			t.Fatal(err)
		}
	}
	if err := atomicLink(generation, filepath.Join(base, "active-runtime")); err != nil {
		t.Fatal(err)
	}
	for _, p := range []string{"containerd/config.toml", "crictl.yaml"} {
		if err := os.WriteFile(e.path("/etc/"+p), []byte("stock"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	bin := t.TempDir()
	plugin := "io.containerd.cri.v1 runtime linux - ok\n"
	if !criOK {
		plugin = "io.containerd.cri.v1 runtime linux - error\n"
	}
	for name, script := range map[string]string{
		"systemctl": "#!/bin/sh\nexit 0\n",
		"ctr":       "#!/bin/sh\nprintf '" + plugin + "'\n",
	} {
		if err := os.WriteFile(filepath.Join(bin, name), []byte(script), 0755); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", bin)
	return e
}

func TestReadyNodeRestartDoesNotCycleContainerdAndKubelet(t *testing.T) {
	e := fakeRuntimeHost(t, true)
	if !e.runtimeSettled(Runtime{ImageVersion: "v1"}) {
		t.Fatal("daemon restart on a ready node restarts the container runtime and kubelet")
	}
	if e.runtimeSettled(Runtime{ImageVersion: "v2"}) {
		t.Fatal("a different selected generation was treated as already running")
	}
	e.State.Upgrade = &Transaction{Target: Runtime{ImageVersion: "v1"}, Stage: "runtime_switch"}
	if e.runtimeSettled(Runtime{ImageVersion: "v1"}) {
		t.Fatal("in-flight runtime transaction skipped its refresh and restart")
	}
}

func TestUnhealthyRuntimeStillGetsRestarted(t *testing.T) {
	e := fakeRuntimeHost(t, false)
	if e.runtimeSettled(Runtime{ImageVersion: "v1"}) {
		t.Fatal("broken CRI left unrepaired on resume")
	}
	e = fakeRuntimeHost(t, true)
	if err := os.Remove(e.path("/var/lib/extensions/kubernetes.raw")); err != nil {
		t.Fatal(err)
	}
	if e.runtimeSettled(Runtime{ImageVersion: "v1"}) {
		t.Fatal("missing runtime extension left unmerged on resume")
	}
	e = fakeRuntimeHost(t, true)
	if err := os.Remove(e.path("/etc/crictl.yaml")); err != nil {
		t.Fatal(err)
	}
	if e.runtimeSettled(Runtime{ImageVersion: "v1"}) {
		t.Fatal("missing runtime configuration left unwritten on resume")
	}
}
