// Package kube is the Kubernetes reboot interlock: kubelet (kubeadm sysext)
// or k0s starting, running or stopping means the node may carry workloads,
// so it reboots through kured (cordon, drain, one node at a time) instead.
//
// A unit waiting to be restarted (activating, sub-state auto-restart) is
// crash-looping: its node is NotReady, has nothing to drain and cannot run
// kured, so it does not count. That covers a kubeadm kubelet restarting every
// 10 s before `kubeadm join` writes its config, and kubelet or k0s broken by
// the update the boot deadline rolls back.
package kube

import (
	"strings"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/sys"
)

// Units are the Kubernetes services the interlock looks at, in order.
var Units = []string{"kubelet.service", "k0scontroller.service", "k0sworker.service"}

// Busy returns the first Kubernetes unit that is active, activating (but not
// waiting to restart), deactivating, reloading or refreshing, and its state.
// quiet adds 2>/dev/null to the systemctl calls.
func Busy(h *sys.Host, quiet bool) (unit, state string, busy bool) {
	for _, u := range Units {
		s, _ := h.Output(quiet, "systemctl", "is-active", u)
		switch s {
		case "activating":
			// auto-restart, or auto-restart-queued (systemd 254+).
			if sub, _ := h.Output(quiet, "systemctl", "show", "-P", "SubState", u); strings.HasPrefix(sub, "auto-restart") {
				continue
			}
			return u, s, true
		case "active", "deactivating", "reloading", "refreshing":
			return u, s, true
		}
	}
	return "", "", false
}

// Interlock is systemd-sysupdate-reboot.service's ExecCondition=: exit 1
// (skip the nightly reboot) while a Kubernetes unit runs.
func Interlock(h *sys.Host, _ []string) int {
	if u, s, busy := Busy(h, false); busy {
		h.Printf("%s is %s: leaving the reboot to kured\n", u, s)
		return 1
	}
	return 0
}
