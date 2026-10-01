package main

import (
	"testing"
)

func TestHealthyControllerCommitsDespitePendingWorkerMigration(t *testing.T) {
	old, next := Runtime{ImageVersion: "old"}, Runtime{ImageVersion: "next"}
	s := State{Profile: "complete", Role: "controller", Phase: "upgrading_healthy", Active: old, Revision: 4, Upgrade: &Transaction{Target: next, Stage: "healthy"}}
	if err := s.commitHealthyRuntime(true); err != nil {
		t.Fatal(err)
	}
	if s.Active.ImageVersion != "next" || s.Prior == nil || s.Prior.ImageVersion != "old" || s.Upgrade != nil || s.Phase != "ready" || s.PendingWorkers == nil {
		t.Fatal("verified controller remains frozen behind remote worker")
	}
	if s.WorkerUpgradeError != "automatic_worker_updates_unavailable" {
		t.Fatal("stock cutover falsely promised automatic worker migration")
	}
	if s.upgradeAction("next") != "start" {
		t.Fatal("manual worker updates blocked healthy controller lifecycle")
	}
}
func TestFleetPreflightRejectsUnsupportedExistingWorkerSkew(t *testing.T) {
	for _, version := range []string{"1.33.9", "1.38.1", "2.0.0"} {
		if supportedWorkerSkew("1.37.1", version) == nil {
			t.Fatalf("irreversible step accepted unsupported worker %s", version)
		}
	}
	for _, version := range []string{"1.36.5", "1.37.1", "1.35.7", "1.34.9"} {
		if err := supportedWorkerSkew("1.37.1", version); err != nil {
			t.Fatal(err)
		}
	}
	if supportedWorkerSkew("1.37.1", "") == nil {
		t.Fatal("unknown worker version guessed safe")
	}
}

func TestSingleNodeUpgradeDoesNotInventPendingWorkers(t *testing.T) {
	s := State{Profile: "complete", Role: "controller", Active: Runtime{ImageVersion: "old"}, PendingWorkers: &Runtime{ImageVersion: "stale"}, WorkerUpgradeError: "old_remote_error", Upgrade: &Transaction{Target: Runtime{ImageVersion: "next"}, Stage: "healthy"}}
	if err := s.commitHealthyRuntime(false); err != nil {
		t.Fatal(err)
	}
	if s.Active.ImageVersion != "next" || s.Phase != "ready" || s.PendingWorkers != nil || s.WorkerUpgradeError != "" {
		t.Fatal("real single-node commit retained fictional remote work")
	}
}
