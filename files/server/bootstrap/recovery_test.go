package main

import "testing"

func TestUpgradeRecoveryCannotChangeMigratedTarget(t *testing.T) {
	for _, role := range []string{"controller", "worker"} {
		s := State{Profile: "complete", Role: role, Phase: "failed", Upgrade: &Transaction{Target: Runtime{ImageVersion: "pinned"}}}
		for _, stage := range []string{"verify_payloads", "staged"} {
			s.Upgrade.Stage = stage
			if got := s.upgradeAction("corrected"); got != "replace" {
				t.Fatalf("rejected safe %s correction: %q", stage, got)
			}
		}
		for _, stage := range []string{"snapshot", "control_plane", "runtime", "healthy"} {
			s.Upgrade.Stage = stage
			if got := s.upgradeAction("different"); got != "" {
				t.Fatalf("changed migrated %s target", stage)
			}
			if got := s.upgradeAction("pinned"); got != "resume" {
				t.Fatalf("cannot resume %s pinned transaction: %q", stage, got)
			}
		}
		s.Upgrade.Stage = "unknown"
		if s.upgradeAction("pinned") != "" {
			t.Fatal("accepted unknown migration state")
		}
	}
	s := State{Profile: "complete", Role: "unassigned", Phase: "ready"}
	if s.upgradeAction("new") != "" {
		t.Fatal("unassigned node upgraded")
	}
	s.Role = "controller"
	if s.upgradeAction("new") != "start" {
		t.Fatal("ready controller cannot upgrade")
	}
	s.Profile = "core"
	if s.upgradeAction("new") != "" {
		t.Fatal("Core activated upgrade")
	}
}
func TestInitializeRecoveryNeverChangesWorkerOrMigratingRole(t *testing.T) {
	s := State{Profile: "complete", Role: "controller", Phase: "failed"}
	if s.initializeAction() != "resume" {
		t.Fatal("failed controller initialization cannot resume")
	}
	s.Upgrade = &Transaction{Stage: "snapshot"}
	if s.initializeAction() != "" {
		t.Fatal("initialize bypassed durable migration")
	}
	s.Upgrade = nil
	s.Role = "worker"
	if s.initializeAction() != "" {
		t.Fatal("worker recovery initialized another controller")
	}
	s.Role = "controller"
	s.Phase = "ready"
	if s.initializeAction() != "" {
		t.Fatal("ready controller reinitialized")
	}
	s.Profile = "core"
	s.Phase = "failed"
	if s.initializeAction() != "" {
		t.Fatal("Core initialized a controller")
	}
	s.Profile = "complete"
	s.Role = "unassigned"
	s.Phase = "awaiting_owner"
	if s.initializeAction() != "" {
		t.Fatal("unassigned host initialized through the control socket; load() already commits its role")
	}
}
