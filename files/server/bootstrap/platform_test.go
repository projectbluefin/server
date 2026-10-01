package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

func TestSelectBaselineWithoutHostGit(t *testing.T) {
	e := Engine{Root: t.TempDir()}
	source := e.path("/usr/share/bluefin-server/baseline.git")
	if err := os.MkdirAll(source, 0755); err != nil {
		t.Fatal(err)
	}
	t.Setenv("GIT_AUTHOR_NAME", "test")
	t.Setenv("GIT_AUTHOR_EMAIL", "test@example.invalid")
	t.Setenv("GIT_COMMITTER_NAME", "test")
	t.Setenv("GIT_COMMITTER_EMAIL", "test@example.invalid")
	git := func(args ...string) string {
		t.Helper()
		out, err := exec.Command("git", append([]string{"--git-dir=" + source}, args...)...).CombinedOutput()
		if err != nil {
			t.Fatalf("fixture git: %v %s", err, out)
		}
		return strings.TrimSpace(string(out))
	}
	git("init", "--bare", "--quiet", "--initial-branch=baseline")
	tree := git("mktree")
	commit := git("commit-tree", tree, "-m", "signed baseline fixture")
	git("update-ref", "refs/heads/baseline", commit)
	e.Profile.BaselineCommit = commit
	files := map[string]string{}
	if err := filepath.WalkDir(source, func(path string, entry os.DirEntry, err error) error {
		if err != nil || entry.IsDir() {
			return err
		}
		body, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(body)
		name, err := filepath.Rel(source, path)
		files[filepath.ToSlash(name)] = hex.EncodeToString(sum[:])
		return err
	}); err != nil {
		t.Fatal(err)
	}
	body, err := json.Marshal(map[string]any{"schema": 1, "commit": commit, "files": files})
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(e.path("/usr/share/bluefin-server/baseline-integrity.json"), body, 0644); err != nil {
		t.Fatal(err)
	}
	bin := t.TempDir()
	for _, name := range []string{"cp", "chmod", "sync"} {
		path, err := exec.LookPath(name)
		if err != nil {
			t.Fatal(err)
		}
		if err := os.Symlink(path, filepath.Join(bin, name)); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("PATH", bin)
	t.Cleanup(func() {
		filepath.WalkDir(e.Root, func(path string, entry os.DirEntry, err error) error {
			if err == nil && entry.IsDir() {
				os.Chmod(path, 0700)
			}
			return nil
		})
	})
	if err := e.selectBaseline(); err != nil {
		t.Fatalf("signed baseline selection requires an unshipped binary: %v", err)
	}
	selected := e.path("/var/lib/bluefin/server/baselines/baseline.git")
	revision, err := os.ReadFile(filepath.Join(selected, "refs/heads/baseline"))
	if err != nil || strings.TrimSpace(string(revision)) != commit {
		t.Fatalf("wrong selected release baseline: %q %v", revision, err)
	}
	if err := e.selectBaseline(); err != nil {
		t.Fatalf("retained baseline failed on restart: %v", err)
	}
	e.Profile.BaselineCommit = strings.Repeat("0", 40)
	if err := e.selectBaseline(); err == nil {
		t.Fatal("accepted signed profile/repository revision mismatch")
	}
	e.Profile.BaselineCommit = commit
	object := filepath.Join(selected, "objects", commit[:2], commit[2:])
	if err := os.Chmod(object, 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(object, []byte("corrupted object with unchanged HEAD"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := e.selectBaseline(); err == nil {
		t.Fatal("retained repository corruption bypassed integrity verification")
	}
}

func TestConsoleOAuthRequiresAllNonemptyPrivateFields(t *testing.T) {
	data := map[string][]byte{}
	for _, key := range []string{"client-id", "client-secret", "frontend-url", "allowed-logins", "admin-logins"} {
		data[key] = []byte("configured")
	}
	encode := func() []byte {
		body, err := json.Marshal(map[string]any{"data": data})
		if err != nil {
			t.Fatal(err)
		}
		return body
	}
	if err := validateConsoleOAuth(encode()); err != nil {
		t.Fatal(err)
	}
	for key := range data {
		for _, value := range [][]byte{nil, {}, []byte(" \n")} {
			data[key] = value
			if err := validateConsoleOAuth(encode()); err == nil {
				t.Fatalf("enabled Console with missing or blank %s", key)
			}
		}
		data[key] = []byte("configured")
	}
	for _, body := range [][]byte{nil, []byte("{}"), []byte(`{"data":{"client-secret":"not-base64!"}}`)} {
		if err := validateConsoleOAuth(body); err == nil {
			t.Fatal("enabled Console without valid private configuration")
		}
	}
}

func TestReadyClusterCanUpgradeWhileConsoleAwaitsOAuth(t *testing.T) {
	s := State{Profile: "complete", Role: "controller", Phase: "ready", Handoff: true, ConsoleStatus: "awaiting_oauth"}
	if s.upgradeAction("next") != "start" {
		t.Fatal("optional Console blocked cluster upgrade")
	}
	body, err := json.Marshal(s.status())
	if err != nil {
		t.Fatal(err)
	}
	var status struct {
		Ready bool `json:"ready"`
	}
	if err = json.Unmarshal(body, &status); err != nil || !status.Ready {
		t.Fatal("optional Console made a ready cluster unavailable")
	}
}
