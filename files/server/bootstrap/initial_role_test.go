package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func startupEngine(t *testing.T, profile string) *Engine {
	t.Helper()
	e := &Engine{Root: t.TempDir()}
	path := e.path("/etc/bluefin/server/profile")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(profile), 0600); err != nil {
		t.Fatal(err)
	}
	image := "registry.example/component@sha256:" + strings.Repeat("a", 64)
	p := Profile{Schema: 1, Runtime: Runtime{ImageVersion: "release", Kubernetes: "v1.36.5", Containerd: "2.4.1"}, BaselineCommit: strings.Repeat("a", 40), PauseImage: image, ConsoleImage: image, WorkflowExecutorImage: image, HealthImage: image}
	if err := saveJSON(e.path("/usr/share/bluefin-server/profile.json"), p); err != nil {
		t.Fatal(err)
	}
	return e
}

func TestCompleteStartupCommitsControllerOnlyOnce(t *testing.T) {
	e := startupEngine(t, "complete")
	if err := e.load(); err != nil {
		t.Fatal(err)
	}
	if e.State.Role != "controller" || e.State.Phase != "pending" {
		t.Fatalf("fresh Complete did not select controller: %+v", e.State)
	}
	revision := e.State.Revision
	if err := e.load(); err != nil {
		t.Fatal(err)
	}
	if e.State.Role != "controller" || e.State.Revision != revision {
		t.Fatal("restart recommitted initialization")
	}
}

func TestPrivateJoinPrecedesCompleteInitializationAndInvalidJoinFailsClosed(t *testing.T) {
	valid := Join{APIEndpoint: "192.168.1.2:6443", Token: "abcdef.0123456789abcdef", CAHash: "sha256:" + strings.Repeat("a", 64), ExpiresAt: time.Now().Add(5 * time.Minute), ClusterID: "cluster"}
	for _, variant := range []string{"valid", "expired", "public", "malformed", "readable"} {
		t.Run(variant, func(t *testing.T) {
			e := startupEngine(t, "complete")
			join := valid
			if variant == "expired" {
				join.ExpiresAt = time.Now().Add(-time.Minute)
			}
			if variant == "public" {
				join.APIEndpoint = "8.8.8.8:6443"
			}
			path := e.path("/var/lib/bluefin/server/private-join.json")
			if err := saveJSON(path, join); err != nil {
				t.Fatal(err)
			}
			if variant == "malformed" {
				if err := os.WriteFile(path, []byte("{broken"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			if variant == "readable" {
				if err := os.Chmod(path, 0644); err != nil {
					t.Fatal(err)
				}
			}
			err := e.load()
			if variant == "valid" {
				if err != nil || e.State.Role != "worker" || e.State.ClusterID != join.ClusterID || e.State.ClusterCAHash != join.CAHash {
					t.Fatalf("private join lost precedence: %+v %v", e.State, err)
				}
			} else {
				if err == nil || e.State.Role != "unassigned" {
					t.Fatalf("invalid join initialized instead: %+v %v", e.State, err)
				}
				if _, err := os.Stat(e.path("/var/lib/bluefin/server/state.json")); !os.IsNotExist(err) {
					t.Fatal("invalid join committed durable role")
				}
			}
		})
	}
}

func TestExistingClusterIdentityNeverAdoptedFromUnassignedRehearsal(t *testing.T) {
	for _, marker := range []string{"/etc/kubernetes/pki/ca.crt", "/etc/kubernetes/kubelet.conf", "/etc/kubernetes/admin.conf", "/etc/kubernetes/bootstrap-kubelet.conf", "/var/lib/kubelet/pki/kubelet-client-current.pem", "/var/lib/etcd/member"} {
		t.Run(filepath.Base(marker), func(t *testing.T) {
			e := startupEngine(t, "complete")
			state := e.path("/var/lib/bluefin/server/state.json")
			body := []byte(`{"schema":1,"profile":"complete","role":"unassigned","phase":"awaiting_owner","revision":9,"runtime":{"image_version":"release"},"console_handoff":false}`)
			if err := os.MkdirAll(filepath.Dir(state), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(state, body, 0600); err != nil {
				t.Fatal(err)
			}
			path := e.path(marker)
			if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
				t.Fatal(err)
			}
			if err := os.WriteFile(path, []byte("existing identity"), 0600); err != nil {
				t.Fatal(err)
			}
			if err := e.load(); err == nil {
				t.Fatal("adopted existing cluster under new role")
			}
			after, err := os.ReadFile(state)
			if err != nil || string(after) != string(body) {
				t.Fatal("failure wiped or replaced rehearsal state")
			}
			after, err = os.ReadFile(path)
			if err != nil || string(after) != "existing identity" {
				t.Fatal("failure destroyed cluster identity")
			}
		})
	}
}

func TestCoreAndNoProfileRemainInertInsideHelper(t *testing.T) {
	for _, profile := range []string{"core", ""} {
		e := startupEngine(t, profile)
		if profile == "" {
			if err := os.Remove(e.path("/etc/bluefin/server/profile")); err != nil {
				t.Fatal(err)
			}
		}
		if err := e.load(); err == nil {
			t.Fatal("inert profile selected a cluster role")
		}
		if _, err := os.Stat(e.path("/var/lib/bluefin/server/state.json")); !os.IsNotExist(err) {
			t.Fatal("inert profile created durable state")
		}
	}
}

func TestWorkerRoleRejectsControllerIdentityAndChangedCA(t *testing.T) {
	ca, hash := testClusterCA(t)
	e := startupEngine(t, "complete")
	e.State = State{Schema: 1, Profile: "complete", Role: "worker", ClusterID: "cluster", ClusterCAHash: hash}
	path := e.path("/etc/kubernetes/pki/ca.crt")
	if err := os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		t.Fatal(err)
	}
	other, _ := testClusterCA(t)
	if err := os.WriteFile(path, other, 0600); err != nil {
		t.Fatal(err)
	}
	if err := e.validateHostRole(); err == nil {
		t.Fatal("worker accepted changed CA")
	}
	if err := os.WriteFile(path, ca, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(e.path("/etc/kubernetes/admin.conf"), []byte("admin"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := e.validateHostRole(); err == nil {
		t.Fatal("worker role adopted controller identity")
	}
}

func TestStockReadinessRejectsDifferentConsoleAndExecutorPins(t *testing.T) {
	e := startupEngine(t, "complete")
	if err := loadJSON(e.path("/usr/share/bluefin-server/profile.json"), &e.Profile); err != nil {
		t.Fatal(err)
	}
	for _, name := range []string{"bluefin-console", "workflow-controller"} {
		for _, correct := range []bool{true, false} {
			ref := e.Profile.ConsoleImage
			if !correct {
				ref = "registry.example/component@sha256:" + strings.Repeat("b", 64)
			}
			containerName := "console"
			if name == "workflow-controller" {
				containerName = "workflow-controller"
			}
			container := map[string]any{"name": containerName, "image": ref, "args": []string{"--executor-image=" + ref}}
			// A correctly pinned arbitrary sidecar must not mask the wrong primary.
			sidecar := map[string]any{"name": "unrelated-sidecar", "image": e.Profile.ConsoleImage, "args": []string{"--executor-image=" + e.Profile.WorkflowExecutorImage}}
			body, err := json.Marshal(map[string]any{"spec": map[string]any{"template": map[string]any{"spec": map[string]any{"containers": []any{container, sidecar}}}}})
			if err != nil {
				t.Fatal(err)
			}
			if err := e.validateStockDeployment(name, body); (err == nil) != correct {
				t.Fatalf("%s pin check correct=%v: %v", name, correct, err)
			}
		}
	}
}
