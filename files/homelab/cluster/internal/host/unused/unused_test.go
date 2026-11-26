package unused

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/hosttest"
)

func TestMigrateAppliesThePresetToEachUnitOnce(t *testing.T) {
	stamp := filepath.Join(t.TempDir(), "var", "lib", "bluefin", "disable-unused-migrate.stamp")
	h := hosttest.New(map[string]string{"BLUEFIN_SYSTEMCTL": "sc", "BLUEFIN_DISABLE_UNUSED_STAMP": stamp}, nil)
	if code := Migrate(h.Host, nil); code != 0 {
		t.Fatalf("exit %d: %s", code, h.Err.String())
	}
	var want []string
	for _, u := range Units {
		want = append(want, "sc list-unit-files --no-legend "+u)
		want = append(want, "sc preset --now "+u)
	}
	if got := h.Fake.Calls(); strings.Join(got, "\n") != strings.Join(want, "\n") {
		t.Errorf("calls %q; want %q", got, want)
	}
	for _, c := range h.Fake.Calls() {
		if strings.Contains(c, "preset-all") || strings.Contains(c, " enable") {
			t.Errorf("must only preset its own units: %q", c)
		}
	}
	if _, err := os.Stat(stamp); err != nil {
		t.Errorf("stamp: %v", err)
	}
}

func TestMigrateRetriesNextBootWhenAPresetFails(t *testing.T) {
	stamp := filepath.Join(t.TempDir(), "stamp")
	h := hosttest.New(map[string]string{"BLUEFIN_SYSTEMCTL": "sc", "BLUEFIN_DISABLE_UNUSED_STAMP": stamp}, func(argv []string) (string, int) {
		if len(argv) >= 2 && argv[1] == "preset" && argv[len(argv)-1] == "isnsd.service" {
			return "", 1
		}
		return "", 0
	})
	if code := Migrate(h.Host, nil); code != 1 {
		t.Fatalf("exit %d; want 1", code)
	}
	if len(h.Fake.Calls()) != len(Units)*2 {
		t.Errorf("a failure must not skip the other units: %q", h.Fake.Calls())
	}
	if _, err := os.Stat(stamp); !os.IsNotExist(err) {
		t.Errorf("stamp written after a failure: %v", err)
	}
}
