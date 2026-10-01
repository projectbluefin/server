package main

import "testing"

func TestControllerSchedulingTargetsOnlyKubeadmNoSchedule(t *testing.T) {
	for _, test := range []struct {
		taints  []NodeTaint
		blocked bool
	}{
		{[]NodeTaint{{Key: "node-role.kubernetes.io/control-plane", Effect: "NoSchedule"}}, true},
		{[]NodeTaint{{Key: "node-role.kubernetes.io/control-plane", Effect: "NoExecute"}}, false},
		{[]NodeTaint{{Key: "owner.example/maintenance", Effect: "NoSchedule"}}, false},
		{[]NodeTaint{{Key: "node-role.kubernetes.io/control-plane", Effect: "PreferNoSchedule"}}, false},
		{nil, false},
	} {
		if got := controllerSchedulingTaint(test.taints); got != test.blocked {
			t.Fatalf("controller scheduling decision=%v for %+v", got, test.taints)
		}
	}
}
