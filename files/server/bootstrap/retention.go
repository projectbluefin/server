package main

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
)

func protectedVersions(state State, pending *Runtime) ([]string, error) {
	versions := []string{"%A"}
	add := func(v string) error {
		if v == "" {
			return nil
		}
		if !safeVersion.MatchString(v) {
			return errors.New("invalid_protected_release")
		}
		for _, existing := range versions {
			if existing == v {
				return nil
			}
		}
		versions = append(versions, v)
		return nil
	}
	if err := add(state.Active.ImageVersion); err != nil {
		return nil, err
	}
	if state.Prior != nil {
		if err := add(state.Prior.ImageVersion); err != nil {
			return nil, err
		}
	}
	if pending != nil {
		if err := add(pending.ImageVersion); err != nil {
			return nil, err
		}
	}
	return versions, nil
}
func (e *Engine) protectReleases(pending *Runtime) error {
	e.mu.Lock()
	state := e.State
	e.mu.Unlock()
	versions, err := protectedVersions(state, pending)
	if err != nil {
		return err
	}
	return writeConfiguration(e.path("/etc/sysupdate.d/33-server-bundle.transfer.d/protect.conf"), "[Transfer]\nProtectVersion="+strings.Join(versions, "\nProtectVersion=")+"\n", true)
}
func (e *Engine) enableServerUpdates() error {
	if e.State.Profile != "complete" {
		return nil
	}
	path := e.path("/etc/sysupdate.d/server.feature.d/10-complete.conf")
	if _, err := os.Stat(path); err == nil {
		return nil
	} else if !errors.Is(err, os.ErrNotExist) {
		return err
	}
	return writeConfiguration(path, "[Feature]\nEnabled=true\n", false)
}
func writeConfiguration(path, text string, replace bool) error {
	dir := filepath.Dir(path)
	if err := os.MkdirAll(dir, 0755); err != nil {
		return err
	}
	file, err := os.CreateTemp(dir, ".configuration-")
	if err != nil {
		return err
	}
	temp := file.Name()
	defer os.Remove(temp)
	if err = file.Chmod(0600); err == nil {
		_, err = file.WriteString(text)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	if replace {
		err = os.Rename(temp, path)
	} else {
		err = os.Link(temp, path)
		if errors.Is(err, os.ErrExist) {
			return nil
		}
	}
	if err != nil {
		return err
	}
	directory, err := os.Open(dir)
	if err != nil {
		return err
	}
	defer directory.Close()
	return directory.Sync()
}
