package bootdeadline

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/hosttest"
)

type node struct {
	status   string
	complete bool
	failed   []string
	units    map[string]string
	subs     map[string]string
	ukis     []string
	lock     bool
	fleet    int
}

func run(t *testing.T, n node) (h *hosttest.Host, code int, sentinel string) {
	t.Helper()
	dir := t.TempDir()
	linux := filepath.Join(dir, "boot", "EFI", "Linux")
	if err := os.MkdirAll(linux, 0o755); err != nil {
		t.Fatal(err)
	}
	for _, u := range n.ukis {
		if err := os.WriteFile(filepath.Join(linux, u), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	osRelease := filepath.Join(dir, "os-release")
	if err := os.WriteFile(osRelease, []byte("IMAGE_VERSION=\"26.09.3\"\n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if n.lock {
		if err := os.WriteFile(filepath.Join(dir, "etc-reboot-lock"), nil, 0o644); err != nil {
			t.Fatal(err)
		}
	}
	sentinel = filepath.Join(dir, "run", "reboot-required")
	env := map[string]string{
		"BLUEFIN_BLESS_BOOT":      "bless",
		"BLUEFIN_BOOT_PATH":       filepath.Join(dir, "boot"),
		"BLUEFIN_OS_RELEASE":      osRelease,
		"BLUEFIN_REBOOT_LOCKS":    filepath.Join(dir, "run-reboot-lock") + " " + filepath.Join(dir, "etc-reboot-lock"),
		"BLUEFIN_REBOOT_SENTINEL": sentinel,
		"BLUEFIN_REBOOT_LOCK":     "fleetlock",
	}
	h = hosttest.New(env, func(argv []string) (string, int) {
		line := strings.Join(argv, " ")
		switch {
		case line == "bless status":
			return n.status + "\n", 0
		case line == "systemctl is-active --quiet boot-complete.target":
			if n.complete {
				return "", 0
			}
			return "", 3
		case strings.HasPrefix(line, "systemctl list-units --state=failed"):
			out := ""
			for _, u := range n.failed {
				out += u + " loaded failed failed Test\n"
			}
			return out, 0
		case strings.HasPrefix(line, "systemctl is-active "):
			if s, ok := n.units[argv[2]]; ok {
				return s + "\n", 3
			}
			return "inactive\n", 3
		case strings.HasPrefix(line, "systemctl show -P SubState "):
			return n.subs[argv[4]] + "\n", 0
		case line == "fleetlock acquire":
			return "", n.fleet
		case line == "systemctl --no-block reboot":
			return "", 0
		}
		return "", 127
	})
	return h, Main(h.Host, nil), sentinel
}

func rebooted(h *hosttest.Host) bool {
	for _, c := range h.Fake.Calls() {
		if c == "systemctl --no-block reboot" {
			return true
		}
	}
	return false
}

func acquired(h *hosttest.Host) bool {
	for _, c := range h.Fake.Calls() {
		if c == "fleetlock acquire" {
			return true
		}
	}
	return false
}

func TestDeadline(t *testing.T) {
	const msg = "Bluefin Server 26.09.3 did not reach boot-complete.target before the boot deadline ("
	for _, tc := range []struct {
		name               string
		node               node
		exit               int
		reboot, flag, slot bool
		log                string
	}{
		{"unblessed", node{status: "indeterminate", failed: []string{"a.service", "b.service"}}, 0, true, false, true,
			"<3>" + msg + "failed: a.service b.service); its boot entry is indeterminate; rebooting so systemd-boot falls back after the last try\n"},
		{"bad, hung", node{status: "bad"}, 0, true, false, true, "no unit failed, but the boot never got there); its boot entry is bad"},
		{"good", node{status: "good"}, 0, false, false, false, "<6>boot is good; nothing to do\n"},
		{"not counted", node{status: ""}, 0, false, false, false, "<6>boot is not boot-counted; nothing to do\n"},
		{"complete", node{status: "indeterminate", complete: true}, 0, false, false, false, "<6>boot-complete.target reached; systemd-bless-boot handles the entry\n"},
		{"operator lock", node{status: "indeterminate", lock: true}, 0, false, false, false, "etc-reboot-lock holds reboots, not rebooting\n"},
		{"kubelet", node{status: "indeterminate", units: map[string]string{"kubelet.service": "active"}}, 0, false, true, false, "; kubelet.service is active: flagged "},
		{"starting kubelet", node{status: "indeterminate", units: map[string]string{"kubelet.service": "activating"}, subs: map[string]string{"kubelet.service": "start"}}, 0, false, true, false, "; kubelet.service is activating: flagged "},
		{"crash-looping kubelet", node{status: "indeterminate", units: map[string]string{"kubelet.service": "activating"}, subs: map[string]string{"kubelet.service": "auto-restart"}}, 0, true, false, true, "rebooting so systemd-boot falls back after the last try\n"},
		{"crash-looping k0s", node{status: "indeterminate", units: map[string]string{"k0sworker.service": "activating"}, subs: map[string]string{"k0sworker.service": "auto-restart"}}, 0, true, false, true, ""},
		{"failed kubelet", node{status: "indeterminate", units: map[string]string{"kubelet.service": "failed"}}, 0, true, false, true, ""},
		{"last try with fallback", node{status: "dirty", ukis: []string{"bluefin-server-26.09.4+0-3.efi", "bluefin-server-26.09.3.efi"}}, 0, true, false, true, ""},
		{"last try alone", node{status: "dirty", ukis: []string{"bluefin-server-26.09.4+0-3.efi", ".x.efi"}}, 0, false, false, false,
			"<4>boot entry has no tries left and no other UKI to fall back to; not rebooting\n"},
		{"no slot", node{status: "indeterminate", fleet: 1}, RetryLater, false, false, true, "; no fleet reboot slot, retrying later\n"},
		{"server unreachable", node{status: "indeterminate", fleet: 3}, 0, true, false, true,
			"<4>the FleetLock server could not be reached; the rollback goes ahead without a reboot slot\n"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			h, code, sentinel := run(t, tc.node)
			_, err := os.Stat(sentinel)
			if code != tc.exit || rebooted(h) != tc.reboot || (err == nil) != tc.flag || acquired(h) != tc.slot {
				t.Errorf("exit %d reboot %v flag %v slot %v\n%s", code, rebooted(h), err == nil, acquired(h), h.Out)
			}
			if !strings.Contains(h.Out.String(), tc.log) {
				t.Errorf("log %q lacks %q", h.Out.String(), tc.log)
			}
		})
	}
}
