// Package etcvendor is bluefin-migrate-etc-vendor: one-shot removal of the
// vendor drop-ins older images copied into /etc, now that they ship in /usr.
//
// Images up to this one put the sshd, sysctl and journald drop-ins in the
// factory /etc, which systemd-tmpfiles copies (C) only when missing. A disk
// install keeps /etc across A/B updates, so those copies stayed at the
// version the node first booted. The drop-ins now live in /usr, linked (sshd)
// or read directly (sysctl, journald). This removes a copy only while its
// content is byte-identical to a version an image shipped, so a file an
// operator edited stays, and tmpfiles then links the current one in. It runs
// once; a stamp in /var suppresses later boots.
package etcvendor

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io/fs"
	"os"
	"slices"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/sys"
)

const Stamp = "/var/lib/bluefin/etc-vendor-migrate.stamp"

// Shipped maps each /etc path an older image copied in to the sha256 of
// every version of it a release carried (from v26.09.673, the first FSDK
// image, on), and of the sshd drop-in as #700 left it. Only an exact match
// is removed.
var Shipped = map[string][]string{
	"ssh/sshd_config.d/bluefin-server.conf": {
		"d6db893a293261e9bc1a7ec183378f3199140039258e42ff7f231bcb0f2fc5b2",
		"cd0d2c8586c7fb9825f398990ed46ac32454b54704333485e79e31d6fd03051f",
		"b1c4085814e5b17a9ae70715a822421ebe57e485fd4b77dcb88b6e07558ef217",
		"0e04923abd1f70d8012dd95292ec7f343f17a6e6e41277517072fbe323b19989",
	},
	"sysctl.d/10-console.conf": {
		"815e73d09439ab850feafddda67cb818025d12211ebf6ab28293cacaafa7552e",
	},
	"systemd/journald.conf.d/10-console.conf": {
		"f4ef13fbdd83470bb0a462f525c6fa00d75428ecbafb4346f45bbdbeaee17db3",
	},
}

// Migrate removes etc/<path> for every path in shipped that is a regular
// file with one of its listed hashes, then creates stamp. It returns the
// paths it removed.
func Migrate(etc string, shipped map[string][]string, stamp string) ([]string, error) {
	var removed []string
	for rel, sums := range shipped {
		p := etc + "/" + rel
		fi, err := os.Lstat(p)
		if errors.Is(err, fs.ErrNotExist) {
			continue
		}
		if err != nil {
			return removed, err
		}
		// A link (the new layout) or anything else an operator put there stays.
		if !fi.Mode().IsRegular() {
			continue
		}
		data, err := os.ReadFile(p)
		if err != nil {
			return removed, err
		}
		sum := sha256.Sum256(data)
		if !slices.Contains(sums, hex.EncodeToString(sum[:])) {
			continue
		}
		if err := os.Remove(p); err != nil {
			return removed, err
		}
		removed = append(removed, rel)
	}
	if err := sys.MkdirP(sys.Dir(stamp)); err != nil {
		return removed, err
	}
	return removed, sys.Truncate(stamp)
}

// Main is bluefin-migrate-etc-vendor.
// Test overrides: BLUEFIN_ETC, BLUEFIN_ETC_VENDOR_STAMP.
func Main(h *sys.Host, _ []string) int {
	etc := h.Env("BLUEFIN_ETC", "/etc")
	stamp := h.Env("BLUEFIN_ETC_VENDOR_STAMP", Stamp)
	removed, err := Migrate(etc, Shipped, stamp)
	for _, rel := range removed {
		h.Printf("bluefin-migrate-etc-vendor: removed the unmodified %s/%s; /usr now ships it\n", etc, rel)
	}
	if err != nil {
		h.Eprintf("bluefin-migrate-etc-vendor: %v\n", err)
		return 1
	}
	return 0
}
