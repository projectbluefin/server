// Package unused is bluefin-disable-unused-migrate: on a node that first
// booted an image without 80-bluefin-unused.preset, apply its lines once.
//
// Presets apply on first boot only, so isnsd and systemd-homed, which FSDK's
// implicit "enable" turned on there, stay enabled across A/B updates. This
// runs `systemctl preset --now` on exactly those units: the shipped preset
// disables and stops them, and a node whose own preset (e.g. Ignition's
// 20-ignition.preset) enables one keeps it. It runs once; a stamp in /var
// suppresses later boots.
package unused

import "github.com/projectbluefin/server/files/homelab/cluster/internal/host/sys"

const Stamp = "/var/lib/bluefin/disable-unused-migrate.stamp"

// Units are the units 80-bluefin-unused.preset disables.
var Units = []string{
	"isnsd.socket",
	"isnsd.service",
	"systemd-homed-activate.service",
	"systemd-homed.service",
}

// Migrate is bluefin-disable-unused-migrate.
// Test overrides: BLUEFIN_SYSTEMCTL, BLUEFIN_DISABLE_UNUSED_STAMP.
func Migrate(h *sys.Host, _ []string) int {
	systemctl := h.Env("BLUEFIN_SYSTEMCTL", "systemctl")
	stamp := h.Env("BLUEFIN_DISABLE_UNUSED_STAMP", Stamp)
	failed := false
	for _, unit := range Units {
		// If the unit file is not installed on this image version, nothing to disable.
		if h.Exec(systemctl, "list-unit-files", "--no-legend", unit) != 0 {
			continue
		}
		if h.Exec(systemctl, "preset", "--now", unit) != 0 {
			h.Eprintf("bluefin-disable-unused-migrate: systemctl preset --now %s failed\n", unit)
			failed = true
		}
	}
	if failed {
		// No stamp: try again next boot.
		return 1
	}
	if err := sys.MkdirP(sys.Dir(stamp)); err != nil {
		h.Eprintf("bluefin-disable-unused-migrate: %v\n", err)
		return 1
	}
	if err := sys.Truncate(stamp); err != nil {
		h.Eprintf("bluefin-disable-unused-migrate: %v\n", err)
		return 1
	}
	h.Printf("bluefin-disable-unused-migrate: applied the preset to %d unit(s)\n", len(Units))
	return 0
}
