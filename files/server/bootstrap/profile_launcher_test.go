package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
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

func TestCompleteStagesSignedPayloadWithVendorKeyring(t *testing.T) {
	bwrap, err := exec.LookPath("bwrap")
	if err != nil {
		t.Skip("bubblewrap is required for isolated real base-launcher proof")
	}
	for _, program := range []string{"gpg", "gpgconf", "gpgv", "sha256sum"} {
		if _, err := exec.LookPath(program); err != nil {
			t.Skip(program + " is required for signed payload proof")
		}
	}
	source, err := filepath.Abs("../../os/libexec/bluefin-server-profile")
	if err != nil {
		t.Fatal(err)
	}
	root := t.TempDir()
	home := filepath.Join(root, "gnupg")
	if err := os.Mkdir(home, 0700); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = exec.Command("gpgconf", "--homedir", home, "--kill", "gpg-agent").Run() })
	run := func(command *exec.Cmd) []byte {
		t.Helper()
		output, err := command.CombinedOutput()
		if err != nil {
			t.Fatalf("%v: %v %s", command.Args, err, output)
		}
		return output
	}
	run(exec.Command("gpg", "--homedir", home, "--batch", "--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key", "Profile test <profile@example.invalid>", "ed25519", "sign", "0"))
	keyring := filepath.Join(root, "import-pubring.pgp")
	run(exec.Command("gpg", "--homedir", home, "--batch", "--output", keyring, "--export"))
	for _, override := range []string{"absent", "invalid", "dangling"} {
		t.Run(override, func(t *testing.T) {
			sandbox := t.TempDir()
			etc := filepath.Join(sandbox, "etc")
			variable := filepath.Join(sandbox, "var")
			incoming := filepath.Join(variable, "lib/bluefin/server/runtime/incoming/1")
			for _, directory := range []string{filepath.Join(etc, "bluefin/server"), filepath.Join(etc, "systemd"), incoming} {
				if err := os.MkdirAll(directory, 0755); err != nil {
					t.Fatal(err)
				}
			}
			if err := os.WriteFile(filepath.Join(etc, "bluefin/server/profile"), []byte("complete\n"), 0600); err != nil {
				t.Fatal(err)
			}
			names := []string{"server_1.raw", "server-kubernetes_1.raw", "server-containerd_1.raw", "profile.json"}
			for _, name := range names {
				if err := os.WriteFile(filepath.Join(incoming, name), []byte(name+"\n"), 0600); err != nil {
					t.Fatal(err)
				}
			}
			hash := exec.Command("sha256sum", names...)
			hash.Dir = incoming
			sums := filepath.Join(incoming, "SHA256SUMS")
			if err := os.WriteFile(sums, run(hash), 0600); err != nil {
				t.Fatal(err)
			}
			run(exec.Command("gpg", "--homedir", home, "--batch", "--output", sums+".gpg", "--detach-sign", sums))
			overridePath := filepath.Join(etc, "systemd/import-pubring.pgp")
			switch override {
			case "invalid":
				if err := os.WriteFile(overridePath, []byte("invalid operator keyring"), 0600); err != nil {
					t.Fatal(err)
				}
			case "dangling":
				if err := os.Symlink("/missing-operator-keyring", overridePath); err != nil {
					t.Fatal(err)
				}
			}
			args := []string{"--unshare-user", "--uid", "0", "--gid", "0", "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin", "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib64", "/lib64", "--bind", etc, "/etc", "--bind", variable, "/var", "--tmpfs", "/usr/lib/systemd", "--ro-bind", keyring, "/usr/lib/systemd/import-pubring.pgp", "--ro-bind", source, "/launcher", "--tmpfs", "/run", "--proc", "/proc", "--dev", "/dev", "--dir", "/boot", "--dir", "/efi", "/usr/bin/bash", "/launcher", "--stage=1"}
			output, err := exec.Command(bwrap, args...).CombinedOutput()
			staged := filepath.Join(variable, "lib/bluefin/server/payloads/1/server_1.raw")
			if override != "absent" {
				if err == nil {
					t.Fatal("invalid operator override fell back to the vendor keyring")
				}
				if !strings.Contains(string(output), "gpgv:") || strings.Contains(string(output), "bwrap:") {
					t.Fatalf("operator override was not rejected by signature verification: %v %s", err, output)
				}
				if _, err := os.Stat(staged); !os.IsNotExist(err) {
					t.Fatal("untrusted payload was staged")
				}
				return
			}
			if err != nil {
				t.Fatalf("vendor-signed payload staging failed: %v %s", err, output)
			}
			for _, name := range names {
				content, err := os.ReadFile(filepath.Join(variable, "lib/bluefin/server/payloads/1", name))
				if err != nil || string(content) != name+"\n" {
					t.Fatalf("staged payload %s differs: %q %v", name, content, err)
				}
			}
		})
	}
}
