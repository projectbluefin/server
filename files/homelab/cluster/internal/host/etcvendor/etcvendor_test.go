package etcvendor

import (
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"sort"
	"testing"
)

func sum(s string) string {
	b := sha256.Sum256([]byte(s))
	return hex.EncodeToString(b[:])
}

func write(t *testing.T, p, data string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(p, []byte(data), 0o644); err != nil {
		t.Fatal(err)
	}
}

func TestMigrateRemovesOnlyUnmodifiedShippedCopies(t *testing.T) {
	dir := t.TempDir()
	etc := filepath.Join(dir, "etc")
	shipped := map[string][]string{
		"a.conf":       {sum("old\n"), sum("older\n")},
		"edited.conf":  {sum("old\n")},
		"linked.conf":  {sum("old\n")},
		"missing.conf": {sum("old\n")},
		"d/b.conf":     {sum("b\n")},
	}
	write(t, filepath.Join(etc, "a.conf"), "older\n")
	write(t, filepath.Join(etc, "edited.conf"), "old\n# mine\n")
	write(t, filepath.Join(etc, "d", "b.conf"), "b\n")
	write(t, filepath.Join(dir, "usr.conf"), "old\n")
	if err := os.Symlink(filepath.Join(dir, "usr.conf"), filepath.Join(etc, "linked.conf")); err != nil {
		t.Fatal(err)
	}
	stamp := filepath.Join(dir, "var", "lib", "bluefin", "stamp")

	removed, err := Migrate(etc, shipped, stamp)
	if err != nil {
		t.Fatal(err)
	}
	sort.Strings(removed)
	if len(removed) != 2 || removed[0] != "a.conf" || removed[1] != "d/b.conf" {
		t.Fatalf("removed %q; want [a.conf d/b.conf]", removed)
	}
	for _, kept := range []string{"edited.conf", "linked.conf"} {
		if _, err := os.Lstat(filepath.Join(etc, kept)); err != nil {
			t.Errorf("%s: %v; want it kept", kept, err)
		}
	}
	if _, err := os.Stat(filepath.Join(dir, "usr.conf")); err != nil {
		t.Errorf("the link target was touched: %v", err)
	}
	if _, err := os.Stat(stamp); err != nil {
		t.Errorf("stamp: %v", err)
	}
}

func TestShippedHashesAreFullSHA256(t *testing.T) {
	for rel, sums := range Shipped {
		if len(sums) == 0 {
			t.Errorf("%s: no hashes", rel)
		}
		for _, s := range sums {
			if b, err := hex.DecodeString(s); err != nil || len(b) != sha256.Size {
				t.Errorf("%s: %q is not a sha256", rel, s)
			}
		}
	}
}
