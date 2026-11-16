package main

import (
	"context"
	"errors"
	"io"
	"log/slog"
	"net"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/conf"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/join"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/ops"
)

const (
	goodPass = "correct-horse-battery-staple"
	badPass  = "correct-horse-battery-stapler"
)

func TestNodePassphraseMissing(t *testing.T) {
	for name, dir := range map[string]string{
		"no credentials directory":    "",
		"credential file not present": t.TempDir(),
	} {
		t.Run(name, func(t *testing.T) {
			t.Setenv("CREDENTIALS_DIRECTORY", dir)
			_, err := nodePassphrase(conf.Config{"HOMELAB_ROLE": conf.RoleNode})
			if err == nil {
				t.Fatal("want an error when no passphrase is configured")
			}
			for _, want := range []string{passKey, conf.DefaultPath, credentialKey} {
				if !strings.Contains(err.Error(), want) {
					t.Errorf("error %q does not name %s", err, want)
				}
			}
		})
	}
}

type fakeMinter struct{}

func (fakeMinter) Mint(_ context.Context, _ string) (ops.Grant, error) {
	return ops.Grant{
		Runtime:      ops.RuntimeKubeadm,
		Endpoint:     "cp.local:6443",
		Token:        "abcdef.0123456789abcdef",
		CACertHashes: []string{"sha256:" + strings.Repeat("ab", 32)},
		TTLSeconds:   int(ops.TokenTTL / time.Second),
	}, nil
}

// startJoinServer serves joins on loopback and returns its host:port, the
// form HOMELAB_CONTROL_PLANE takes.
func startJoinServer(t *testing.T, pass string) string {
	t.Helper()
	dir := t.TempDir()
	cert, err := join.LoadOrCreateCert(dir)
	if err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	srv := &join.Server{
		Passphrase: pass,
		Cluster:    "lab",
		Cert:       cert,
		Runtime:    func() string { return ops.RuntimeKubeadm },
		Minter:     fakeMinter{},
		Limiter:    join.NewLimiter(join.DefaultServerLimits, filepath.Join(dir, "failures.json"), nil),
		Log:        slog.New(slog.NewTextHandler(io.Discard, nil)),
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { _ = srv.Serve(ctx, ln); close(done) }()
	t.Cleanup(func() { cancel(); <-done })
	return ln.Addr().String()
}

func joinClient(pass string) *join.Client {
	return &join.Client{
		Passphrase: pass,
		Node:       "node-1",
		Runtime:    ops.RuntimeKubeadm,
		Budget:     join.NewClientBudget(100, time.Hour, nil),
		Timeout:    10 * time.Second,
	}
}

func TestAttemptManualControlPlaneJoins(t *testing.T) {
	addr := startJoinServer(t, goodPass)
	p, err := attempt(context.Background(), joinClient(goodPass), addr)
	if err != nil {
		t.Fatal(err)
	}
	if p.Cluster != "lab" || p.Grant.Runtime != ops.RuntimeKubeadm || p.Grant.Endpoint != "cp.local:6443" {
		t.Errorf("payload %+v", p)
	}
}

func TestAttemptManualControlPlaneWrongPassphrase(t *testing.T) {
	addr := startJoinServer(t, goodPass)
	_, err := attempt(context.Background(), joinClient(badPass), addr)
	if !errors.Is(err, join.ErrNotProven) {
		t.Fatalf("want ErrNotProven, got %v", err)
	}
	if !strings.Contains(err.Error(), "127.0.0.1") {
		t.Errorf("error %q does not name the control plane it tried", err)
	}
}

func TestAttemptManualControlPlaneBadPort(t *testing.T) {
	for _, manual := range []string{"127.0.0.1:0", "127.0.0.1:65536", "127.0.0.1:http"} {
		_, err := attempt(context.Background(), joinClient(goodPass), manual)
		if err == nil || !strings.Contains(err.Error(), "bad port") {
			t.Errorf("%s: want a bad port error, got %v", manual, err)
		}
	}
}
