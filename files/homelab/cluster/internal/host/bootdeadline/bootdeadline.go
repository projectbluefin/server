// Package bootdeadline is bluefin-boot-deadline: reboot a boot-counted boot
// that was not blessed in time.
//
// systemd-sysupdate installs a new UKI with a tries counter
// (bluefin-server-<ver>+3-0.efi). systemd-boot uses up one try each time it
// boots the entry, and systemd-bless-boot drops the counter once
// boot-complete.target is reached. A boot that never gets there keeps its
// counter, but systemd-boot only moves on at the next boot.
//
// bluefin-boot-deadline.timer runs this once the deadline passes, on
// boot-counted boots only. If the boot is still not blessed:
//   - /run/reboot-lock or /etc/reboot-lock: the operator holds reboots; log
//     and stay up;
//   - kubelet or k0s running: touch /run/reboot-required for kured to cordon,
//     drain and reboot the node within its cluster lock. A unit that failed
//     or is crash-looping (waiting to restart) does not count: the node is
//     NotReady, kured cannot run there, and the flag would leave it on the
//     bad image for good;
//   - otherwise reboot, so systemd-boot uses up the next try and, after the
//     last one, falls back to the previous UKI. With a FleetLock server
//     configured it first takes a reboot slot (bluefin-reboot-lock acquire);
//     a refused slot exits 75 and the service runs it again later
//     (RestartForceExitStatus=). An unreachable server (3) does not hold the
//     rollback: the update it rolls back may be what broke the network.
//
// The last try boots as "dirty" (no tries left). It reboots only when another
// UKI still has tries or no counter, so a node with nothing to fall back to
// does not reboot in a loop.
package bootdeadline

import (
	"path/filepath"
	"strings"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/fleetlock"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/kube"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/sys"
)

// RetryLater is the exit status bluefin-boot-deadline.service restarts on.
const RetryLater = 75

// fallback reports another UKI systemd-boot would pick over this one: no
// counter, or tries left.
func fallback(h *sys.Host) bool {
	for _, uki := range sys.Glob(filepath.Join(h.BootPath(), "EFI", "Linux"), "*.efi") {
		if !sys.Exists(uki) {
			continue
		}
		name := filepath.Base(uki)
		plain, _ := filepath.Match("*+0.efi", name)
		done, _ := filepath.Match("*+0-*.efi", name)
		if !plain && !done {
			return true
		}
	}
	return false
}

// Main is bluefin-boot-deadline. Test overrides: BLUEFIN_BLESS_BOOT,
// BLUEFIN_BOOT_PATH, BLUEFIN_OS_RELEASE, BLUEFIN_REBOOT_LOCKS
// (space-separated), BLUEFIN_REBOOT_SENTINEL, BLUEFIN_REBOOT_LOCK (the
// FleetLock client; in-process when unset).
func Main(h *sys.Host, _ []string) int {
	bless := h.Env("BLUEFIN_BLESS_BOOT", "/usr/lib/systemd/systemd-bless-boot")
	sentinel := h.Env("BLUEFIN_REBOOT_SENTINEL", "/run/reboot-required")
	osRelease := h.Env("BLUEFIN_OS_RELEASE", "/usr/lib/os-release")
	locks := sys.Fields(h.Env("BLUEFIN_REBOOT_LOCKS", "/run/reboot-lock /etc/reboot-lock"))

	status, code := h.Output(true, bless, "status")
	if code != 0 {
		status = ""
	}
	switch status {
	case "indeterminate", "bad":
	case "dirty":
		if !fallback(h) {
			h.Log(sys.Warning, "boot entry has no tries left and no other UKI to fall back to; not rebooting")
			return 0
		}
	default:
		shown := status
		if shown == "" {
			shown = "not boot-counted"
		}
		h.Log(sys.Info, "boot is "+shown+"; nothing to do")
		return 0
	}

	if h.Exec("systemctl", "is-active", "--quiet", "boot-complete.target") == 0 {
		h.Log(sys.Info, "boot-complete.target reached; systemd-bless-boot handles the entry")
		return 0
	}

	version := sys.ImageVersion(osRelease)
	if version == "" {
		version = "(unknown version)"
	}
	var failed []string
	units, _ := h.Output(true, "systemctl", "list-units", "--state=failed", "--plain", "--no-legend", "--no-pager")
	for _, line := range strings.Split(units, "\n") {
		if unit, _ := sys.ReadRest(line); unit != "" {
			failed = append(failed, unit)
		}
	}
	why := "no unit failed, but the boot never got there"
	if len(failed) > 0 {
		why = "failed: " + strings.Join(failed, " ")
	}
	msg := "Bluefin Server " + version + " did not reach boot-complete.target before the boot deadline (" + why + "); its boot entry is " + status

	for _, lock := range locks {
		if sys.Exists(lock) {
			h.Log(sys.Warning, msg+"; "+lock+" holds reboots, not rebooting")
			return 0
		}
	}

	if u, s, busy := kube.Busy(h, true); busy {
		if err := sys.MkdirP(sys.Dir(sentinel)); err != nil {
			h.Eprintf("bluefin-boot-deadline: %v\n", err)
			return 1
		}
		if err := sys.Touch(sentinel); err != nil {
			h.Eprintf("bluefin-boot-deadline: %v\n", err)
			return 1
		}
		h.Log(sys.Warning, msg+"; "+u+" is "+s+": flagged "+sentinel+" for kured to drain and reboot")
		return 0
	}

	var rc int
	if client := h.Getenv("BLUEFIN_REBOOT_LOCK"); client != "" {
		rc = h.Exec(client, "acquire")
	} else {
		rc = fleetlock.Main(h, []string{"acquire"})
	}
	switch rc {
	case 0:
	case 3:
		h.Log(sys.Warning, "the FleetLock server could not be reached; the rollback goes ahead without a reboot slot")
	default:
		h.Log(sys.Warning, msg+"; no fleet reboot slot, retrying later")
		return RetryLater
	}

	h.Log(sys.Err, msg+"; rebooting so systemd-boot falls back after the last try")
	return h.Exec("systemctl", "--no-block", "reboot")
}
