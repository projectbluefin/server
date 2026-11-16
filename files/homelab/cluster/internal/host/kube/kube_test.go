package kube

import (
	"testing"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/host/hosttest"
)

func TestInterlock(t *testing.T) {
	for _, tc := range []struct {
		states map[string]string
		subs   map[string]string
		want   int
		says   string
	}{
		{map[string]string{}, nil, 0, ""},
		{map[string]string{"kubelet.service": "failed", "k0sworker.service": "inactive"}, nil, 0, ""},
		{map[string]string{"kubelet.service": "active"}, nil, 1, "kubelet.service is active: leaving the reboot to kured\n"},
		{map[string]string{"k0scontroller.service": "reloading"}, nil, 1, "k0scontroller.service is reloading: leaving the reboot to kured\n"},
		{map[string]string{"k0sworker.service": "deactivating", "kubelet.service": "activating"}, map[string]string{"kubelet.service": "start"}, 1, "kubelet.service is activating: leaving the reboot to kured\n"},
		{map[string]string{"k0sworker.service": "refreshing"}, nil, 1, "k0sworker.service is refreshing: leaving the reboot to kured\n"},
		// Crash-looping (or a kubeadm kubelet before `kubeadm join`): NotReady,
		// kured cannot run there, so the reboot goes ahead.
		{map[string]string{"kubelet.service": "activating"}, map[string]string{"kubelet.service": "auto-restart"}, 0, ""},
		{map[string]string{"k0sworker.service": "activating"}, map[string]string{"k0sworker.service": "auto-restart-queued"}, 0, ""},
		// Only the crash-looping unit is skipped; the next one still counts.
		{map[string]string{"kubelet.service": "activating", "k0scontroller.service": "active"}, map[string]string{"kubelet.service": "auto-restart"}, 1, "k0scontroller.service is active: leaving the reboot to kured\n"},
	} {
		h := hosttest.New(nil, func(argv []string) (string, int) {
			switch argv[1] {
			case "is-active":
				if s, ok := tc.states[argv[2]]; ok {
					return s + "\n", 3
				}
				return "inactive\n", 3
			case "show":
				return tc.subs[argv[4]] + "\n", 0
			}
			return "", 127
		})
		if got := Interlock(h.Host, nil); got != tc.want || h.Out.String() != tc.says {
			t.Errorf("%v %v: exit %d, %q", tc.states, tc.subs, got, h.Out.String())
		}
	}
}
