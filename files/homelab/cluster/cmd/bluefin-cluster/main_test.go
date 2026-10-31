package main

import (
	"context"
	"errors"
	"net/netip"
	"testing"
	"time"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/discover"
	"github.com/projectbluefin/server/files/homelab/cluster/internal/join"
)

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
