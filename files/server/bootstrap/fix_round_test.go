package main

import (
	"os"
	"path/filepath"
	"testing"
)

func TestUpgradeRebootUsesSelectedCommittedGeneration(t *testing.T) {
	old, next := Runtime{ImageVersion: "old"}, Runtime{ImageVersion: "next"}
	for _, stage := range []string{"verify_payloads", "staged", "snapshot", "control_plane"} {
		s := State{Active: old, Upgrade: &Transaction{Target: next, Stage: stage}}
		r, err := s.resumeRuntime("old")
		if err != nil || r.ImageVersion != "old" {
			t.Fatalf("%s lost prior runtime: %+v %v", stage, r, err)
		}
		if _, err = s.resumeRuntime("next"); err == nil {
			t.Fatalf("%s silently accepted early runtime switch", stage)
		}
	}
	for _, stage := range []string{"runtime", "healthy"} {
		s := State{Active: old, Upgrade: &Transaction{Target: next, Stage: stage}}
		r, err := s.resumeRuntime("next")
		if err != nil || r.ImageVersion != "next" {
			t.Fatalf("%s downgraded selected target", stage)
		}
		if _, err = s.resumeRuntime("old"); err == nil {
			t.Fatalf("%s accepted old runtime after migration", stage)
		}
	}
	s := State{Active: old, Upgrade: &Transaction{Target: next, Stage: "runtime_switch"}}
	for _, selected := range []string{"old", "next"} {
		r, err := s.resumeRuntime(selected)
		if err != nil || r.ImageVersion != selected {
			t.Fatal("interrupted atomic switch did not preserve observed generation")
		}
	}
	if _, err := s.resumeRuntime("unrelated"); err == nil {
		t.Fatal("accepted unrelated generation")
	}
}
func TestPublicBluefinParentRepairsPrivateUmaskWithoutOpeningState(t *testing.T) {
	e := Engine{Root: t.TempDir()}
	parent := e.path("/var/lib/bluefin")
	state := filepath.Join(parent, "server")
	if err := os.MkdirAll(state, 0700); err != nil {
		t.Fatal(err)
	}
	if err := os.Chmod(parent, 0700); err != nil {
		t.Fatal(err)
	}
	if err := e.prepareStateDirectories(); err != nil {
		t.Fatal(err)
	}
	p, _ := os.Stat(parent)
	s, _ := os.Stat(state)
	if p.Mode().Perm() != 0755 || s.Mode().Perm() != 0711 {
		t.Fatalf("Stock data path not traversable parent=%o state=%o", p.Mode().Perm(), s.Mode().Perm())
	}
	for _, bad := range []string{"symlink", "writable"} {
		root := t.TempDir()
		en := Engine{Root: root}
		path := en.path("/var/lib/bluefin")
		os.MkdirAll(filepath.Dir(path), 0755)
		if bad == "symlink" {
			os.Symlink(t.TempDir(), path)
		} else {
			os.Mkdir(path, 0777)
			os.Chmod(path, 0777)
		}
		if en.prepareStateDirectories() == nil {
			t.Fatalf("accepted unsafe %s public parent", bad)
		}
	}
}
func TestWorkerDrainDoesNotTrustSpoofedPlatformLabel(t *testing.T) {
	p := DrainedPod{}
	p.Metadata.Labels = map[string]string{"bluefin.io/platform": "true"}
	p.Status.Phase = "Running"
	if drainedPodsSafe([]DrainedPod{p}) == nil {
		t.Fatal("spoofable platform label bypassed user workload drain")
	}
	p.Metadata.OwnerReferences = []PodOwner{{Kind: "DaemonSet"}}
	if err := drainedPodsSafe([]DrainedPod{p}); err != nil {
		t.Fatal("real daemon pod blocks worker upgrade")
	}
	p.Metadata.OwnerReferences = nil
	p.Metadata.Annotations = map[string]string{"kubernetes.io/config.mirror": "hash"}
	if err := drainedPodsSafe([]DrainedPod{p}); err != nil {
		t.Fatal("mirror pod blocks upgrade")
	}
}
func TestEnrollmentRenewalCannotReplaceRegisteredOrDifferentClusterWorker(t *testing.T) {
	s := State{Profile: "complete", Role: "worker", Phase: "failed", ClusterID: "cluster"}
	if s.joinAction("cluster", false) != "renew" {
		t.Fatal("expired never-joined worker cannot receive physical renewal")
	}
	if s.joinAction("other", false) != "" || s.joinAction("cluster", true) != "" {
		t.Fatal("renewal replaced cluster or established kubelet identity")
	}
	s.Upgrade = &Transaction{}
	if s.joinAction("cluster", false) != "" {
		t.Fatal("enrollment bypassed upgrade")
	}
	s.Upgrade = nil
	s.Role = "controller"
	if s.joinAction("cluster", false) != "" {
		t.Fatal("controller role changed during enrollment")
	}
}
