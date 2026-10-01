package main

import (
	"errors"
	"os"
	"path/filepath"
	"syscall"
	"time"
)

func (s State) resumeRuntime(selected string) (Runtime, error) {
	if s.Upgrade == nil {
		return s.Active, nil
	}
	tx := s.Upgrade
	switch tx.Stage {
	case "verify_payloads", "staged", "snapshot", "control_plane":
		if selected == s.Active.ImageVersion {
			return s.Active, nil
		}
	case "runtime_switch":
		if selected == s.Active.ImageVersion {
			return s.Active, nil
		}
		if selected == tx.Target.ImageVersion {
			return tx.Target, nil
		}
	case "runtime", "healthy":
		if selected == tx.Target.ImageVersion {
			return tx.Target, nil
		}
	default:
		return Runtime{}, errors.New("invalid_upgrade_stage")
	}
	return Runtime{}, errors.New("upgrade_runtime_generation_mismatch")
}
func (e *Engine) resumeUpgradeRuntime() error {
	link, err := os.Readlink(e.path("/var/lib/bluefin/server/active-runtime"))
	if err != nil {
		return errors.New("upgrade_selected_generation_missing")
	}
	selected := filepath.Base(link)
	runtime, err := e.State.resumeRuntime(selected)
	if err != nil {
		return err
	}
	// The durable migration stage and observed atomic selector agree before any
	// refresh/restart. Do not downgrade or choose a different target after migration.
	if err = e.prepareRuntime(runtime); err != nil {
		return err
	}
	return e.waitAPIReady()
}
func (e *Engine) waitAPIReady() error {
	config := "/etc/kubernetes/admin.conf"
	if e.State.Role == "worker" {
		config = "/etc/kubernetes/kubelet.conf"
	}
	deadline := time.Now().Add(3 * time.Minute)
	for {
		if run("kubectl", "--kubeconfig="+config, "--request-timeout=5s", "get", "--raw=/readyz") == nil {
			return nil
		}
		if time.Now().After(deadline) {
			return errors.New("api_readiness_stalled")
		}
		time.Sleep(time.Second)
	}
}
func (e *Engine) prepareStateDirectories() error {
	for _, entry := range []struct {
		path string
		mode os.FileMode
	}{{"/var/lib/bluefin", 0755}, {"/var/lib/bluefin/server", 0711}} {
		path := e.path(entry.path)
		info, err := os.Lstat(path)
		if errors.Is(err, os.ErrNotExist) {
			if err = os.MkdirAll(path, entry.mode); err != nil {
				return err
			}
			info, err = os.Lstat(path)
		}
		if err != nil {
			return err
		}
		stat, ok := info.Sys().(*syscall.Stat_t)
		if !info.IsDir() || !ok || stat.Uid != uint32(os.Geteuid()) || info.Mode().Perm()&0022 != 0 {
			return errors.New("unsafe_server_state_directory")
		}
		if err = os.Chmod(path, entry.mode); err != nil {
			return err
		}
	}
	return nil
}
