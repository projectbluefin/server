package main

import (
	"errors"
	"os"
	"syscall"
	"time"
)

func (e *Engine) requireUninitializedHost() error {
	if e.State.ClusterID != "" || e.State.ClusterCAHash != "" || e.State.Handoff || e.State.Upgrade != nil || e.State.PendingWorkers != nil {
		return errors.New("unassigned_state_has_cluster_identity")
	}
	for _, path := range []string{"/etc/kubernetes/pki/ca.crt", "/etc/kubernetes/pki/ca.key", "/etc/kubernetes/kubelet.conf", "/etc/kubernetes/bootstrap-kubelet.conf", "/etc/kubernetes/admin.conf", "/etc/kubernetes/manifests/kube-apiserver.yaml", "/var/lib/kubelet/pki/kubelet-client-current.pem", "/var/lib/etcd/member", "/etc/bluefin/server/kubeadm-init.yaml"} {
		if _, err := os.Lstat(e.path(path)); !errors.Is(err, os.ErrNotExist) {
			return errors.New("cluster_exists_without_committed_role")
		}
	}
	return nil
}

func (e *Engine) selectInitialRole(at time.Time) error {
	if e.State.Role != "unassigned" {
		return errors.New("role_already_committed")
	}
	if err := e.requireUninitializedHost(); err != nil {
		return err
	}
	candidate := e.State
	role := "controller"
	path := e.path("/var/lib/bluefin/server/private-join.json")
	info, err := os.Lstat(path)
	if err == nil {
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !info.Mode().IsRegular() || info.Mode().Perm()&0077 != 0 || !ok || stat.Uid != uint32(os.Geteuid()) {
			return errors.New("private_join_not_private")
		}
		var join Join
		if err = loadJSON(path, &join); err != nil {
			return errors.New("private_join_invalid")
		}
		if err = join.validate(at); err != nil {
			return err
		}
		role = "worker"
		candidate.ClusterID = join.ClusterID
		candidate.ClusterCAHash = join.CAHash
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	if err = candidate.commitRole(role, candidate.Revision); err != nil {
		return err
	}
	e.State = candidate
	return e.persist()
}

func (e *Engine) validateHostRole() error {
	if e.State.Role == "worker" {
		for _, path := range []string{"/etc/kubernetes/admin.conf", "/etc/kubernetes/manifests/kube-apiserver.yaml", "/var/lib/etcd/member"} {
			if _, err := os.Lstat(e.path(path)); !errors.Is(err, os.ErrNotExist) {
				return errors.New("controller_identity_conflicts_with_worker_role")
			}
		}
	}
	body, err := os.ReadFile(e.path("/etc/kubernetes/pki/ca.crt"))
	if errors.Is(err, os.ErrNotExist) {
		if e.hasWorkerIdentity() || (e.State.Role == "controller" && e.State.ClusterID != "") {
			return errors.New("cluster_ca_missing")
		}
		return nil
	}
	if err != nil {
		return err
	}
	hash, err := certificateDiscoveryHash(body)
	if err != nil {
		return err
	}
	e.mu.Lock()
	defer e.mu.Unlock()
	if e.State.ClusterCAHash != "" && e.State.ClusterCAHash != hash {
		return errors.New("cluster_ca_identity_changed")
	}
	if e.State.ClusterCAHash == "" {
		e.State.ClusterCAHash = hash
		return e.persist()
	}
	return nil
}
