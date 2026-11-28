// Command bluefin-host is Bluefin Server's runtime helpers in one static
// binary. It runs as /usr/bin/bluefin-host <command> or through a symlink
// named after the helper it replaces (/usr/libexec/bluefin-update-status ->
// ../bin/bluefin-host), so unit files and documentation keep their paths.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/bootdeadline"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/bootorigin"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/diskless"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/etcmodes"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/firstboot"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/fleetlock"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/hostname"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/kmods"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/kube"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/sys"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/sysextfetch"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/unused"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/updatepending"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/updatestatus"
)

type command func(h *sys.Host, args []string) int

// cLocale are the commands whose shell versions exported LC_ALL=C, which
// their commands (systemctl, journalctl, depmod, gpgv...) inherited;
// kured-flag runs bluefin-update-pending.
var cLocale = map[string]bool{
	"boot-deadline": true, "boot-origin": true, "diskless-update-check": true,
	"firstboot-credentials": true, "hostname": true, "reboot-lock": true,
	"sysext-fetch": true, "sysext-modules": true, "update-pending": true,
	"update-status": true, "kured-flag": true,
}

// helpers are installed as /usr/libexec/bluefin-<name> symlinks.
var helpers = map[string]command{
	"boot-deadline":          bootdeadline.Main,
	"boot-origin":            bootorigin.Main,
	"diskless-update-check":  diskless.Check,
	"disable-unused-migrate": unused.Migrate,
	"firstboot-credentials":  firstboot.Main,
	"hostname":               hostname.Main,
	"reboot-lock":            fleetlock.Main,
	"repair-etc-modes":       etcmodes.Main,
	"sysext-fetch":           sysextfetch.Main,
	"sysext-modules":         kmods.Main,
	"update-pending":         updatepending.Main,
	"update-status":          updatestatus.Main,
	"update-status-migrate":  updatestatus.Migrate,
}

// units are run by unit files as /usr/bin/bluefin-host <name>.
var units = map[string]command{
	"boot-is-good":      fleetlock.ReleaseCondition,
	"kube-interlock":    kube.Interlock,
	"kured-flag":        updatepending.KuredFlag,
	"mask-uki-transfer": diskless.MaskUKITransfer,
}

func helper(name string) (command, bool) {
	cmd, ok := helpers[name]
	if !ok {
		return nil, false
	}
	return withLocale(name, cmd), true
}

func withLocale(name string, cmd command) command {
	if cLocale[name] {
		return func(h *sys.Host, args []string) int {
			os.Setenv("LC_ALL", "C")
			return cmd(h, args)
		}
	}
	return cmd
}

func lookup(name string) (command, bool) {
	if cmd, ok := helper(strings.TrimPrefix(name, "bluefin-")); ok {
		return cmd, true
	}
	cmd, ok := units[name]
	if !ok {
		return nil, false
	}
	return withLocale(name, cmd), true
}

func usage() int {
	var names []string
	for name := range helpers {
		names = append(names, name)
	}
	for name := range units {
		names = append(names, name)
	}
	sort.Strings(names)
	fmt.Fprintf(os.Stderr, "usage: bluefin-host <command> [args...]\ncommands: %s\n", strings.Join(names, " "))
	return 2
}

func run(argv []string) int {
	if name, ok := strings.CutPrefix(filepath.Base(argv[0]), "bluefin-"); ok {
		if cmd, ok := helper(name); ok {
			return cmd(sys.New(), argv[1:])
		}
	}
	if len(argv) < 2 {
		return usage()
	}
	cmd, ok := lookup(argv[1])
	if !ok {
		return usage()
	}
	return cmd(sys.New(), argv[2:])
}

func main() { os.Exit(run(os.Args)) }
