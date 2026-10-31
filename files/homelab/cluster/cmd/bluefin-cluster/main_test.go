package main

import (
	"context"
	"errors"
	"net/netip"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/conf"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/discover"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/join"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/ops"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/passphrase"
)

// withRoot points ops.Root (every host path) at a fresh directory and
// creates files under it.
func withRoot(t *testing.T, files ...string) string {
	t.Helper()
	root := t.TempDir()
	orig := ops.Root
	ops.Root = root
	t.Cleanup(func() { ops.Root = orig })
	for _, f := range files {
		p := filepath.Join(root, f)
		if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
			t.Fatal(err)
		}
		if err := os.WriteFile(p, nil, 0o600); err != nil {
			t.Fatal(err)
		}
	}
	return root
}

func TestJoined(t *testing.T) {
	for _, tc := range []struct {
		name  string
		files []string
		want  bool
	}{
		{"fresh node", nil, false},
		{"marker", []string{joinedMarker}, true},
		{"kubeadm join bootstrapped kubelet", []string{ops.KubeadmKubelet}, true},
		{"k0s worker bootstrapped kubelet", []string{ops.K0sTokenFile, ops.K0sKubelet}, true},
		// Written before k0s-first-boot.service starts: if that failed, or
		// the token expired unused, the node must ask for a fresh one.
		{"k0s token alone", []string{ops.K0sTokenFile}, false},
		{"kubeadm bootstrap kubeconfig alone", []string{"/etc/kubernetes/bootstrap-kubelet.conf"}, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			withRoot(t, tc.files...)
			if got := joined(); got != tc.want {
				t.Errorf("joined() = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestTryCandidates(t *testing.T) {
	a1 := netip.MustParseAddrPort("192.0.2.1:6447")
	a2 := netip.MustParseAddrPort("[2001:db8::1]:6447")
	b1 := netip.MustParseAddrPort("192.0.2.2:6447")
	c1 := netip.MustParseAddrPort("192.0.2.3:6447")
	cands := []discover.Candidate{
		{Name: "a", Addrs: []netip.AddrPort{a1, a2}},
		{Name: "b", Addrs: []netip.AddrPort{b1}},
		{Name: "c", Addrs: []netip.AddrPort{c1}},
	}
	refused := errors.New("connection refused")
	budget := &join.ErrBudget{RetryAfter: time.Minute}
	for _, tc := range []struct {
		name    string
		results map[netip.AddrPort]error // nil: joins
		tried   []netip.AddrPort
		joined  bool
		budget  bool
	}{
		{"first address joins", map[netip.AddrPort]error{a1: nil}, []netip.AddrPort{a1}, true, false},
		{"unreachable address falls through to the next one", map[netip.AddrPort]error{a1: refused, a2: nil}, []netip.AddrPort{a1, a2}, true, false},
		// An impostor (or another cluster) listed first must not hide the
		// control plane: skip the rest of it, go on with the next.
		{"not proven skips that candidate", map[netip.AddrPort]error{a1: join.ErrNotProven, b1: nil}, []netip.AddrPort{a1, b1}, true, false},
		{"every candidate not proven", map[netip.AddrPort]error{a1: join.ErrNotProven, b1: join.ErrNotProven, c1: join.ErrNotProven}, []netip.AddrPort{a1, b1, c1}, false, false},
		{"exhausted budget ends the round", map[netip.AddrPort]error{a1: join.ErrNotProven, b1: budget}, []netip.AddrPort{a1, b1}, false, true},
		{"nothing answers", map[netip.AddrPort]error{a1: refused, a2: refused, b1: refused, c1: refused}, []netip.AddrPort{a1, a2, b1, c1}, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			var tried []netip.AddrPort
			p, err := tryCandidates(context.Background(), func(_ context.Context, addr netip.AddrPort) (join.Payload, error) {
				tried = append(tried, addr)
				err, ok := tc.results[addr]
				if !ok {
					t.Errorf("unexpected address %s", addr)
					return join.Payload{}, errors.New("unexpected address")
				}
				if err != nil {
					return join.Payload{}, err
				}
				return join.Payload{Cluster: addr.String()}, nil
			}, cands)
			if (err == nil) != tc.joined {
				t.Fatalf("joined %v, err %v", err == nil, err)
			}
			if tc.joined && p.Cluster != tried[len(tried)-1].String() {
				t.Errorf("payload from %s, last tried %s", p.Cluster, tried[len(tried)-1])
			}
			var be *join.ErrBudget
			if errors.As(err, &be) != tc.budget {
				t.Errorf("budget error %v: %v", tc.budget, err)
			}
			if len(tried) != len(tc.tried) {
				t.Fatalf("tried %v, want %v", tried, tc.tried)
			}
			for i := range tried {
				if tried[i] != tc.tried[i] {
					t.Fatalf("tried %v, want %v", tried, tc.tried)
				}
			}
		})
	}
}

func TestControlPlanePassphrase(t *testing.T) {
	const strong = "Correct Horse battery_staple-orbit"
	for _, tc := range []struct {
		name   string
		conf   conf.Config
		stored string // existing passFile content, "" for none
		want   string // "" without err: a generated one
		err    bool
	}{
		{"operator-chosen, normalised and stored", conf.Config{passKey: strong}, "", "correct-horse-battery-staple-orbit", false},
		{"operator-chosen beats the stored one", conf.Config{passKey: strong}, "old-words-here-now\n", "correct-horse-battery-staple-orbit", false},
		{"operator-chosen too weak", conf.Config{passKey: "short pass"}, "", "", true},
		{"operator-chosen not ASCII", conf.Config{passKey: "café crème brûlée soufflé"}, "", "", true},
		{"stored one kept", conf.Config{}, "Alpha Bravo charlie delta\n", "alpha-bravo-charlie-delta", false},
		{"generated on first start", conf.Config{}, "", "", false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			root := withRoot(t)
			file := filepath.Join(root, passFile)
			if err := os.MkdirAll(filepath.Dir(file), 0o700); err != nil {
				t.Fatal(err)
			}
			if tc.stored != "" {
				if err := os.WriteFile(file, []byte(tc.stored), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			got, err := controlPlanePassphrase(tc.conf)
			if (err != nil) != tc.err {
				t.Fatalf("err %v, want error %v", err, tc.err)
			}
			if tc.err {
				if err != nil && strings.Contains(err.Error(), tc.conf[passKey]) {
					t.Errorf("error leaks the passphrase: %v", err)
				}
				return
			}
			if tc.want != "" && got != tc.want {
				t.Errorf("got %q, want %q", got, tc.want)
			}
			if tc.want == "" && len(strings.Split(got, "-")) != passphrase.DefaultWords {
				t.Errorf("generated %q: want %d words", got, passphrase.DefaultWords)
			}
			// What serve hands out is what a restart reads back; a stored
			// one is left as it is.
			want := got + "\n"
			if tc.stored != "" && tc.conf[passKey] == "" {
				want = tc.stored
			}
			if data, err := os.ReadFile(file); err != nil || string(data) != want {
				t.Errorf("stored %q (%v), want %q", data, err, want)
			}
			fi, err := os.Stat(file)
			if err != nil {
				t.Fatal(err)
			}
			if fi.Mode().Perm() != 0o600 {
				t.Errorf("passphrase file mode %v, want 0600", fi.Mode().Perm())
			}
		})
	}
}

func TestNodePassphrase(t *testing.T) {
	for _, tc := range []struct {
		name       string
		conf       conf.Config
		credential string // "" for none
		want       string
		err        bool
	}{
		{"from homelab.conf", conf.Config{passKey: "Four Words From_Console"}, "", "four-words-from-console", false},
		{"homelab.conf beats the credential", conf.Config{passKey: "four words from console"}, "other words entirely here", "four-words-from-console", false},
		{"from the credential", conf.Config{}, "four words from console\n", "four-words-from-console", false},
		{"none", conf.Config{}, "", "", true},
		{"not ASCII", conf.Config{passKey: "naïve words"}, "", "", true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			dir := t.TempDir()
			t.Setenv("CREDENTIALS_DIRECTORY", dir)
			if tc.credential != "" {
				if err := os.WriteFile(filepath.Join(dir, credentialKey), []byte(tc.credential), 0o600); err != nil {
					t.Fatal(err)
				}
			}
			got, err := nodePassphrase(tc.conf)
			if (err != nil) != tc.err || got != tc.want {
				t.Errorf("got %q, %v; want %q, error %v", got, err, tc.want, tc.err)
			}
		})
	}
}

func TestDNSSDBodyCarriesNoSecrets(t *testing.T) {
	got := dnssdBody("lab", "kubeadm", "6447")
	want := "# bluefin-cluster serve: the homelab join service (no secrets here).\n" +
		"[Service]\nName=%H\nType=" + discover.ServiceType + "\nPort=6447\nTxtText=v=1 cluster=lab runtime=kubeadm\n"
	if got != want {
		t.Errorf("dnssd body:\n%s\nwant:\n%s", got, want)
	}
}
