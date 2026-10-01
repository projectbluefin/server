package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"testing"
)

func TestCoreAndNoProfileDoNotInspectOrMutateServerAncestors(t *testing.T) {
	bwrap, err := exec.LookPath("bwrap")
	if err != nil {
		t.Skip("bubblewrap is required for isolated real base-launcher proof")
	}
	source, err := filepath.Abs("../../os/libexec/bluefin-server-profile")
	if err != nil {
		t.Fatal(err)
	}
	for _, profile := range []string{"", "core"} {
		t.Run(profile, func(t *testing.T) {
			root := t.TempDir()
			etc := filepath.Join(root, "etc")
			variable := filepath.Join(root, "var")
			creds := filepath.Join(root, "creds")
			for _, p := range []string{etc, variable, creds, filepath.Join(variable, "lib/bluefin")} {
				if err = os.MkdirAll(p, 0755); err != nil {
					t.Fatal(err)
				}
			}
			ancestor := filepath.Join(variable, "lib/bluefin")
			if err = os.Chmod(ancestor, 0777); err != nil {
				t.Fatal(err)
			}
			if profile != "" {
				if err = os.WriteFile(filepath.Join(creds, "bluefin.server-profile"), []byte(profile), 0600); err != nil {
					t.Fatal(err)
				}
			}
			args := []string{"--unshare-user", "--uid", "0", "--gid", "0", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--bind", etc, "/etc", "--bind", variable, "/var", "--ro-bind", creds, "/creds", "--ro-bind", source, "/launcher", "--tmpfs", "/run", "--proc", "/proc", "--dev", "/dev", "--dir", "/boot", "--dir", "/efi", "--setenv", "CREDENTIALS_DIRECTORY", "/creds", "/usr/bin/bash", "/launcher"}
			output, err := exec.Command(bwrap, args...).CombinedOutput()
			if err != nil {
				t.Fatalf("inert profile failed: %v %s", err, output)
			}
			st, _ := os.Stat(ancestor)
			if st.Mode().Perm() != 0777 {
				t.Fatal("inert profile repaired unrelated ancestor")
			}
			if _, err = os.Stat(filepath.Join(ancestor, "server")); !os.IsNotExist(err) {
				t.Fatal("inert profile activated Server state")
			}
		})
	}
}
