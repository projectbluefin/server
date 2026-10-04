package join

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/ops"
)

func TestMintLimiterCapsWithinTheWindow(t *testing.T) {
	now := time.Unix(1_700_000_000, 0)
	m := NewMintLimiter(2, time.Hour, func() time.Time { return now })
	if !m.Allow() || !m.Allow() {
		t.Fatal("the first two mints in the window must be allowed")
	}
	if m.Allow() {
		t.Fatal("a third mint inside the window must be refused")
	}
	now = now.Add(time.Hour - time.Second)
	if m.Allow() {
		t.Fatal("a refused mint must not be recorded, and the window has not passed")
	}
	now = now.Add(time.Second)
	if !m.Allow() {
		t.Fatal("mints older than the window must stop counting")
	}
}

func TestMintCapRefusesAProvenNodeWithoutMinting(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits, func(s *Server) {
		s.Mints = NewMintLimiter(1, time.Hour, nil)
	})
	if _, err := client(goodPass).Join(context.Background(), ts.addr); err != nil {
		t.Fatal(err)
	}
	waitSlotFree(ts.limiter, SourceKey(ts.addr.Addr()))
	cl := client(goodPass)
	cl.Budget = NewClientBudget(1, time.Hour, nil)
	_, err := cl.Join(context.Background(), ts.addr)
	var se *ServerError
	if !errors.As(err, &se) || se.Code != ErrCodeBusy || se.RetryAfter != 60 {
		t.Fatalf("want busy with a one-minute retry once the mint cap is reached, got %v", err)
	}
	if got := ts.minter.calls.Load(); got != 1 {
		t.Fatalf("minted %d tokens, want 1: the cap must stop the mint", got)
	}
	if got := ts.limiter.Failures(); got != 0 {
		t.Fatalf("a node that proved the passphrase must not count as a failure, got %d", got)
	}
	if _, ok := cl.Budget.Take(); !ok {
		t.Fatal("the client must refund its guess once the server proved the passphrase")
	}
	if !strings.Contains(ts.logs.String(), "join token mint limit reached") {
		t.Fatalf("mint cap not logged:\n%s", ts.logs.String())
	}
}

type failingMinter struct{}

func (failingMinter) Mint(context.Context, string) (ops.Grant, error) {
	return ops.Grant{}, errors.New("kubeadm token create: exit status 1")
}

func TestMintFailureIsUnavailable(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits, func(s *Server) {
		s.Minter = failingMinter{}
	})
	_, err := client(goodPass).Join(context.Background(), ts.addr)
	var se *ServerError
	if !errors.As(err, &se) || se.Code != ErrCodeUnavailable || se.RetryAfter != 30 {
		t.Fatalf("want unavailable with a 30s retry when minting fails, got %v", err)
	}
	if got := ts.limiter.Failures(); got != 0 {
		t.Fatalf("a mint failure must not be charged to the node, got %d failures", got)
	}
	if !strings.Contains(ts.logs.String(), "minting a join token failed") {
		t.Fatalf("mint failure not logged:\n%s", ts.logs.String())
	}
}

func TestNoLocalRuntimeYetIsUnavailableAndCostsNoGuess(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits, func(s *Server) {
		s.Runtime = func() string { return "" }
	})
	cl := client(goodPass)
	cl.Budget = NewClientBudget(1, time.Hour, nil)
	_, err := cl.Join(context.Background(), ts.addr)
	var se *ServerError
	if !errors.As(err, &se) || se.Code != ErrCodeUnavailable || se.RetryAfter != 30 {
		t.Fatalf("want unavailable with a 30s retry before the control plane has a runtime, got %v", err)
	}
	if got := ts.minter.calls.Load(); got != 0 {
		t.Fatalf("minted %d tokens before the control plane had a runtime", got)
	}
	if got := ts.limiter.Failures(); got != 0 {
		t.Fatalf("refused before the PAKE, so no failure may be recorded, got %d", got)
	}
	if _, ok := cl.Budget.Take(); !ok {
		t.Fatal("a refusal before the PAKE must not spend the client's guess")
	}
}
