package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestWorkerCannotBecomeController(t *testing.T) {
	s := State{Schema: 1, Profile: "complete", Role: "worker", Phase: "joining", Revision: 4}
	if err := s.commitRole("controller", 4); err == nil {
		t.Fatal("worker role switched to controller")
	}
	if s.Role != "worker" || s.Revision != 4 {
		t.Fatal("rejected change mutated state")
	}
}
func TestRoleCommitRejectsStaleClaim(t *testing.T) {
	s := State{Schema: 1, Profile: "complete", Role: "unassigned", Revision: 2}
	if err := s.commitRole("worker", 1); err == nil {
		t.Fatal("stale pairing accepted")
	}
	if err := s.commitRole("worker", 2); err != nil {
		t.Fatal(err)
	}
	if err := s.commitRole("controller", 2); err == nil {
		t.Fatal("concurrent owner claim replaced worker")
	}
}
func TestInvalidJoinNeverCommitsRole(t *testing.T) {
	now := time.Date(2026, 9, 30, 12, 0, 0, 0, time.UTC)
	valid := Join{APIEndpoint: "192.168.1.2:6443", Token: "abcdef.0123456789abcdef", CAHash: "sha256:" + strings.Repeat("a", 64), ExpiresAt: now.Add(time.Minute), ClusterID: "controller-uid"}
	for _, mutate := range []func(*Join){
		func(j *Join) { j.ExpiresAt = now }, func(j *Join) { j.CAHash = "unsafe-skip-ca" },
		func(j *Join) { j.Token = "bad" }, func(j *Join) { j.APIEndpoint = "https://evil.example:6443/path" },
		func(j *Join) { j.APIEndpoint = "8.8.8.8:6443" }, func(j *Join) { j.ClusterID = "" },
	} {
		j := valid
		mutate(&j)
		if err := j.validate(now); err == nil {
			t.Fatalf("accepted unsafe join %+v", j)
		}
	}
	if err := valid.validate(now); err != nil {
		t.Fatal(err)
	}
}
func TestDurableStateRoundTripAndPrivateModes(t *testing.T) {
	path := filepath.Join(t.TempDir(), "state.json")
	s := State{Schema: 1, Profile: "complete", Role: "worker", Phase: "ready", Revision: 8, ClusterID: "cluster"}
	if err := saveJSON(path, &s); err != nil {
		t.Fatal(err)
	}
	var restored State
	if err := loadJSON(path, &restored); err != nil {
		t.Fatal(err)
	}
	if restored.Role != "worker" || restored.Revision != 8 {
		t.Fatal("lost durable role")
	}
	st, _ := os.Stat(path)
	if st.Mode().Perm() != 0600 {
		t.Fatal("state is not private")
	}
}
func TestStatusDoesNotIncludePrivateEnrollment(t *testing.T) {
	s := State{Schema: 1, Profile: "complete", Role: "worker", Phase: "failed", Error: "join_failed"}
	body, err := json.Marshal(s.status())
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(body), "token") {
		t.Fatal("status leaked credentials")
	}
	if !strings.Contains(string(body), "join_failed") {
		t.Fatal("status hid failure")
	}
}
func TestUpgradeRejectsDowngradeAndMinorJump(t *testing.T) {
	for _, next := range []string{"v1.35.9", "v1.38.1", "v1.36.4"} {
		if err := checkSkew("v1.36.5", next); err == nil {
			t.Fatalf("accepted unsafe upgrade %s", next)
		}
	}
	for _, next := range []string{"v1.36.6", "v1.37.1"} {
		if err := checkSkew("v1.36.5", next); err != nil {
			t.Fatal(err)
		}
	}
}
func TestRuntimeSelectionRetainsPreviousPair(t *testing.T) {
	root := t.TempDir()
	e := Engine{Root: root}
	makePair := func(v string) Runtime {
		p := filepath.Join(root, "var/lib/bluefin/server/payloads", v)
		os.MkdirAll(p, 0700)
		os.WriteFile(filepath.Join(p, "k.raw"), []byte(v), 0600)
		os.WriteFile(filepath.Join(p, "c.raw"), []byte(v), 0600)
		return Runtime{ImageVersion: v, Kubernetes: "v1.36.5", Containerd: "2.4.1", KubernetesFile: "k.raw", ContainerdFile: "c.raw"}
	}
	first, second := makePair("a"), makePair("b")
	if err := e.selectRuntime(first); err != nil {
		t.Fatal(err)
	}
	if err := e.selectRuntime(second); err != nil {
		t.Fatal(err)
	}
	link := filepath.Join(root, "var/lib/extensions/kubernetes.raw")
	content, err := os.ReadFile(link)
	if err != nil || string(content) != "b" {
		t.Fatalf("active pair not selected %q %v", content, err)
	}
	if _, err := os.Stat(filepath.Join(root, "var/lib/bluefin/server/generations/a/kubernetes.raw")); err != nil {
		t.Fatal("previous runtime removed", err)
	}
}
func TestStrictJSONRejectsUnknownAndTrailingInput(t *testing.T) {
	for _, body := range []string{`{"expected_revision":1,"command":"reset"}`, `{"expected_revision":1} {}`} {
		var req RevisionRequest
		if err := decodeJSON(strings.NewReader(body), &req); err == nil {
			t.Fatal("accepted unknown/trailing input")
		}
	}
}
