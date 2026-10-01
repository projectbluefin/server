package main

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestProtectsBootedActivePreviousAndPendingReleases(t *testing.T) {
	previous := Runtime{ImageVersion: "old"}
	pending := Runtime{ImageVersion: "next"}
	s := State{Active: Runtime{ImageVersion: "active"}, Prior: &previous}
	e := Engine{Root: t.TempDir(), State: s}
	if err := e.protectReleases(&pending); err != nil {
		t.Fatal(err)
	}
	config, err := os.ReadFile(e.path("/etc/sysupdate.d/33-server-bundle.transfer.d/protect.conf"))
	if err != nil {
		t.Fatal(err)
	}
	retained := map[string]bool{}
	for _, line := range strings.Split(string(config), "\n") {
		if v, ok := strings.CutPrefix(line, "ProtectVersion="); ok {
			if v != "%A" && !safeVersion.MatchString(v) {
				t.Fatalf("sysupdate rejects protected version %q", v)
			}
			retained[v] = true
		}
	}
	for _, v := range []string{"%A", "active", "old", "next"} {
		if !retained[v] {
			t.Fatalf("release %s is vulnerable to inbox collection", v)
		}
	}
	pending.ImageVersion = "active"
	versions, err := protectedVersions(s, &pending)
	if err != nil {
		t.Fatal(err)
	}
	count := 0
	for _, v := range versions {
		if v == "active" {
			count++
		}
	}
	if count != 1 {
		t.Fatal("duplicate active/pending retention")
	}
	pending.ImageVersion = "next\nProtectVersion="
	if _, err = protectedVersions(s, &pending); err == nil {
		t.Fatal("accepted sysupdate config injection")
	}
}
func TestCompleteDoesNotOverwriteOperatorUpdateOptOut(t *testing.T) {
	e := Engine{Root: t.TempDir(), State: State{Profile: "complete"}}
	path := e.path("/etc/sysupdate.d/server.feature.d/10-complete.conf")
	if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
		t.Fatal(err)
	}
	original := "[Feature]\nEnabled=false\n# Explicit operator maintenance decision\n"
	if err := os.WriteFile(path, []byte(original), 0600); err != nil {
		t.Fatal(err)
	}
	if err := e.enableServerUpdates(); err != nil {
		t.Fatal(err)
	}
	after, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	if string(after) != original {
		t.Fatal("restart overrode operator update opt-out")
	}
}
