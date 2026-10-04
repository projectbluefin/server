package join

import (
	"bytes"
	"context"
	"crypto/tls"
	"errors"
	"io"
	"log/slog"
	"net"
	"net/netip"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"filippo.io/cpace"

	"github.com/projectbluefin/server/files/homelab/cluster/internal/ops"
)

const (
	goodPass = "correct-horse-battery-staple"
	badPass  = "correct-horse-battery-stapler"
	token    = "abcdef.0123456789abcdef"
)

type fakeMinter struct{ calls atomic.Int32 }

func (f *fakeMinter) Mint(_ context.Context, node string) (ops.Grant, error) {
	f.calls.Add(1)
	return ops.Grant{
		Runtime:      ops.RuntimeKubeadm,
		Endpoint:     "cp.local:6443",
		Token:        token,
		CACertHashes: []string{"sha256:" + strings.Repeat("ab", 32)},
		TTLSeconds:   int(ops.TokenTTL / time.Second),
	}, nil
}

type testServer struct {
	addr    netip.AddrPort
	minter  *fakeMinter
	limiter *Limiter
	logs    *bytes.Buffer
	cert    tls.Certificate
}

func startServer(t *testing.T, pass string, limits Limits, opts ...func(*Server)) *testServer {
	t.Helper()
	dir := t.TempDir()
	cert, err := LoadOrCreateCert(dir)
	if err != nil {
		t.Fatal(err)
	}
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	ts := &testServer{
		minter:  &fakeMinter{},
		limiter: NewLimiter(limits, filepath.Join(dir, "failures.json"), nil),
		logs:    &bytes.Buffer{},
		cert:    cert,
	}
	var mu sync.Mutex
	srv := &Server{
		Passphrase: pass,
		Cluster:    "lab",
		Cert:       cert,
		Runtime:    func() string { return ops.RuntimeKubeadm },
		Minter:     ts.minter,
		Limiter:    ts.limiter,
		Log:        slog.New(slog.NewTextHandler(lockedWriter{&mu, ts.logs}, nil)),
	}
	for _, o := range opts {
		o(srv)
	}
	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() { _ = srv.Serve(ctx, ln); close(done) }()
	t.Cleanup(func() { cancel(); <-done })
	ts.addr = netip.MustParseAddrPort(ln.Addr().String())
	return ts
}

type lockedWriter struct {
	mu *sync.Mutex
	w  io.Writer
}

func (l lockedWriter) Write(p []byte) (int, error) {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.w.Write(p)
}

func client(pass string) *Client {
	return &Client{Passphrase: pass, Node: "node-1", Runtime: ops.RuntimeKubeadm, Budget: NewClientBudget(100, time.Hour, nil), Timeout: 10 * time.Second}
}

func TestGoodPassphraseGetsAToken(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	p, err := client(goodPass).Join(context.Background(), ts.addr)
	if err != nil {
		t.Fatal(err)
	}
	if p.Cluster != "lab" || p.Grant.Token != token || p.Grant.Endpoint != "cp.local:6443" {
		t.Fatalf("unexpected payload %+v", p)
	}
	if got := ts.limiter.Failures(); got != 0 {
		t.Fatalf("a successful join must not count as a failure, got %d", got)
	}
	if strings.Contains(ts.logs.String(), token) || strings.Contains(ts.logs.String(), goodPass) {
		t.Fatal("token or passphrase in the server log")
	}
}

func TestWrongPassphraseIsRejectedWithoutLeaking(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	cl := client(badPass)
	var wire bytes.Buffer
	cl.Dial = recordingDial(&wire)
	p, err := cl.Join(context.Background(), ts.addr)
	if !errors.Is(err, ErrNotProven) {
		t.Fatalf("want ErrNotProven, got %v", err)
	}
	if p.Grant.Token != "" {
		t.Fatal("a payload was returned")
	}
	if ts.minter.calls.Load() != 0 {
		t.Fatal("a token was minted for a wrong passphrase")
	}
	if ts.limiter.Failures() != 1 {
		t.Fatalf("want 1 failure, got %d", ts.limiter.Failures())
	}
	for _, secret := range []string{goodPass, badPass, "correct", "staple"} {
		if bytes.Contains(wire.Bytes(), []byte(secret)) || strings.Contains(ts.logs.String(), secret) {
			t.Fatalf("%q on the wire or in the log", secret)
		}
	}
}

// The control plane proves the passphrase first, so a node never sends its
// confirmation to a server that does not know it.
func TestRogueServerLearnsNoConfirmation(t *testing.T) {
	ts := startServer(t, badPass, DefaultServerLimits)
	_, err := client(goodPass).Join(context.Background(), ts.addr)
	if !errors.Is(err, ErrNotProven) {
		t.Fatalf("want ErrNotProven, got %v", err)
	}
	time.Sleep(100 * time.Millisecond)
	if !strings.Contains(ts.logs.String(), "did not prove") {
		t.Fatalf("server should see no confirmation; log: %s", ts.logs.String())
	}
}

func recordingDial(w *bytes.Buffer) func(ctx context.Context, addr string) (net.Conn, error) {
	return func(ctx context.Context, addr string) (net.Conn, error) {
		var d net.Dialer
		c, err := d.DialContext(ctx, "tcp", addr)
		if err != nil {
			return nil, err
		}
		return &tapConn{Conn: c, w: w}, nil
	}
}

type tapConn struct {
	net.Conn
	w *bytes.Buffer
}

func (t *tapConn) Read(p []byte) (int, error) {
	n, err := t.Conn.Read(p)
	t.w.Write(p[:n])
	return n, err
}

func (t *tapConn) Write(p []byte) (int, error) {
	t.w.Write(p)
	return t.Conn.Write(p)
}

// relay terminates the node's TLS with its own certificate and forwards the
// plaintext frames over a second TLS connection to the real control plane:
// a machine-in-the-middle that knows nothing but sees everything.
func relay(t *testing.T, upstream netip.AddrPort) func(ctx context.Context, addr string) (net.Conn, error) {
	cert, err := LoadOrCreateCert(t.TempDir())
	if err != nil {
		t.Fatal(err)
	}
	return func(ctx context.Context, _ string) (net.Conn, error) {
		nodeSide, mitmSide := net.Pipe()
		go func() {
			defer mitmSide.Close()
			down := tls.Server(mitmSide, &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS13})
			if down.Handshake() != nil {
				return
			}
			up, err := tls.Dial("tcp", upstream.String(), &tls.Config{InsecureSkipVerify: true, MinVersion: tls.VersionTLS13})
			if err != nil {
				return
			}
			defer up.Close()
			go func() { _, _ = io.Copy(up, down); up.Close() }()
			_, _ = io.Copy(down, up)
		}()
		return nodeSide, nil
	}
}

func TestRelayWithMismatchedTLSBindingFails(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	cl := client(goodPass)
	cl.Dial = relay(t, ts.addr)
	_, err := cl.Join(context.Background(), ts.addr)
	if !errors.Is(err, ErrNotProven) {
		t.Fatalf("relay: want ErrNotProven, got %v", err)
	}
	if ts.minter.calls.Load() != 0 {
		t.Fatal("a relayed exchange got a token minted")
	}
}

// rawSession speaks the protocol by hand so a test can replay messages.
func rawSession(t *testing.T, addr netip.AddrPort, frames ...any) []serverReply {
	t.Helper()
	c, err := tls.Dial("tcp", addr.String(), &tls.Config{InsecureSkipVerify: true, MinVersion: tls.VersionTLS13})
	if err != nil {
		t.Fatal(err)
	}
	defer c.Close()
	_ = c.SetDeadline(time.Now().Add(5 * time.Second))
	var replies []serverReply
	for _, f := range frames {
		if err := writeFrame(c, f); err != nil {
			break
		}
		var r serverReply
		if err := readFrame(c, &r); err != nil {
			break
		}
		replies = append(replies, r)
		if r.Error != "" {
			break
		}
	}
	return replies
}

// waitSlotFree blocks until the server has released the per-source slot held
// by a previous connection from src. Two tests replay a captured exchange from
// the same source immediately after an honest exchange; on a loaded runner the
// server goroutine may not have returned yet, so the replay's Begin reports
// busy and the replay never runs. Poll the slot with a deadline so the test
// stays deterministic instead of sleeping. See issue #391.
func waitSlotFree(l *Limiter, src string) {
	deadline := time.Now().Add(2 * time.Second)
	for time.Now().Before(deadline) {
		if !l.inUse(src) {
			return
		}
		time.Sleep(time.Millisecond)
	}
}

func TestForgedConfirmationIsDenied(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	if _, err := client(goodPass).Join(context.Background(), ts.addr); err != nil {
		t.Fatal(err)
	}
	// The honest exchange above charged the source's slot; wait for the server
	// goroutine to release it before replaying from the same source, or Begin
	// reports busy and the replay is rejected before it runs. See issue #391.
	waitSlotFree(ts.limiter, "127.0.0.1")
	// A forged confirmation after a well-formed hello.
	msgA, _, err := cpace.Start(goodPass, cpace.NewContextInfo(nodeIdentity, cpIdentity, nil))
	if err != nil {
		t.Fatal(err)
	}
	h := hello{V: Version, Node: "node-1", Runtime: ops.RuntimeKubeadm, PAKE: msgA}
	before := ts.minter.calls.Load()
	replies := rawSession(t, ts.addr, h, clientConfirm{Confirm: bytes.Repeat([]byte{2}, tagLen)})
	if len(replies) != 2 || replies[1].Error != ErrCodeDenied || replies[1].Sealed != nil {
		t.Fatalf("replay: want denied, got %+v", replies)
	}
	if ts.minter.calls.Load() != before {
		t.Fatal("replay minted a token")
	}
}

func TestReplayOfACapturedExchangeAcrossConnections(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	// An attacker who captured the plaintext of a real exchange (msgA and
	// tagC) replays it on a new connection: the new exporter changes the
	// CPace generator and the transcript, so tagC no longer verifies.
	var captured struct {
		h hello
		c clientConfirm
	}
	conn, err := tls.Dial("tcp", ts.addr.String(), &tls.Config{InsecureSkipVerify: true, MinVersion: tls.VersionTLS13})
	if err != nil {
		t.Fatal(err)
	}
	b, _ := bindingOf(conn.ConnectionState(), conn.ConnectionState().PeerCertificates[0].Raw)
	k := honestClient(t, conn, b, &captured.h)
	captured.c = clientConfirm{Confirm: tag(k.client, k.th)}
	_ = writeFrame(conn, captured.c)
	var sealed serverReply
	if err := readFrame(conn, &sealed); err != nil || sealed.Sealed == nil {
		t.Fatalf("honest exchange failed: %v %+v", err, sealed)
	}
	conn.Close()
	// Wait for the honest exchange's slot to be released before replaying from
	// the same source. On a loaded runner the server goroutine may not have
	// returned yet, which would make the replay's Begin report busy. See #391.
	waitSlotFree(ts.limiter, "127.0.0.1")

	before := ts.minter.calls.Load()
	replies := rawSession(t, ts.addr, captured.h, captured.c)
	if len(replies) != 2 || replies[1].Error != ErrCodeDenied {
		t.Fatalf("replay across connections: want denied, got %+v", replies)
	}
	if ts.minter.calls.Load() != before {
		t.Fatal("replay minted a token")
	}
}

// TestReplayFromSameSourceUnderHeldSlot reproduces issue #391 deterministically.
// A replay opened from the same source while the honest exchange's slot is still
// held is rejected as busy — the flake the two replay tests guard against — and
// the same replay is served (denied) once the slot has been released.
func TestReplayFromSameSourceUnderHeldSlot(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)

	// Half-finish an honest exchange: send the hello, read the server's PAKE
	// reply, but never send the confirmation. The server charges the source,
	// runs PAKE, and blocks reading the confirmation, so the slot is held.
	conn, err := tls.Dial("tcp", ts.addr.String(), &tls.Config{InsecureSkipVerify: true, MinVersion: tls.VersionTLS13})
	if err != nil {
		t.Fatal(err)
	}
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	msgA, _, err := cpace.Start(goodPass, cpace.NewContextInfo(nodeIdentity, cpIdentity, nil))
	if err != nil {
		t.Fatal(err)
	}
	h := hello{V: Version, Node: "node-1", Runtime: ops.RuntimeKubeadm, PAKE: msgA}
	if err := writeFrame(conn, h); err != nil {
		t.Fatal(err)
	}
	var reply serverReply
	if err := readFrame(conn, &reply); err != nil {
		t.Fatalf("read PAKE reply: %v", err)
	}
	if reply.Error != "" || len(reply.PAKE) != msgBLen {
		t.Fatalf("expected a PAKE reply, got %+v", reply)
	}
	if !ts.limiter.inUse("127.0.0.1") {
		t.Fatal("a half-finished honest exchange must hold the source slot")
	}

	// While the slot is still held, a replay from the same source is rejected as
	// busy. This is the flake the two replay tests avoid by waiting first.
	busy := rawSession(t, ts.addr, h, clientConfirm{Confirm: bytes.Repeat([]byte{2}, tagLen)})
	if len(busy) != 1 || busy[0].Error != ErrCodeBusy {
		t.Fatalf("replay under held slot: want busy, got %+v", busy)
	}

	// Release the slot the way the server does: closing the connection ends the
	// handler, which runs Done. Wait until the slot is actually free, then the
	// same replay is served and denied instead of rejected as busy.
	conn.Close()
	waitSlotFree(ts.limiter, "127.0.0.1")
	replies := rawSession(t, ts.addr, h, clientConfirm{Confirm: bytes.Repeat([]byte{2}, tagLen)})
	if len(replies) != 2 || replies[1].Error != ErrCodeDenied || replies[1].Sealed != nil {
		t.Fatalf("replay after release: want denied, got %+v", replies)
	}
	if ts.minter.calls.Load() != 0 {
		t.Fatal("replay minted a token")
	}
}

func TestRateLimitPerSource(t *testing.T) {
	ts := startServer(t, goodPass, Limits{PerSource: 3, PerSourceWindow: time.Hour, Global: 100, GlobalWindow: time.Hour})
	for i := 0; i < 3; i++ {
		if _, err := client(badPass).Join(context.Background(), ts.addr); !errors.Is(err, ErrNotProven) {
			t.Fatalf("attempt %d: %v", i, err)
		}
	}
	_, err := client(goodPass).Join(context.Background(), ts.addr)
	var se *ServerError
	if !errors.As(err, &se) || se.Code != ErrCodeRateLimited || se.RetryAfter <= 0 {
		t.Fatalf("want rate-limited with a retry delay even for the right passphrase, got %v", err)
	}
	if ts.minter.calls.Load() != 0 {
		t.Fatal("minted while rate-limited")
	}
}

func TestClientBudgetSpansCandidates(t *testing.T) {
	budget := NewClientBudget(2, time.Hour, nil)
	var servers []*testServer
	for i := 0; i < 3; i++ {
		servers = append(servers, startServer(t, badPass, DefaultServerLimits))
	}
	for i, ts := range servers {
		cl := client(goodPass)
		cl.Budget = budget
		_, err := cl.Join(context.Background(), ts.addr)
		var be *ErrBudget
		if i < 2 && !errors.Is(err, ErrNotProven) {
			t.Fatalf("candidate %d: %v", i, err)
		}
		if i == 2 && !errors.As(err, &be) {
			t.Fatalf("third rogue candidate must hit the shared budget, got %v", err)
		}
	}
}

func TestLimiterAtomicPersistentAndRefundsOnlyItsOwnAttempt(t *testing.T) {
	now := time.Unix(1_000_000, 0)
	clock := func() time.Time { return now }
	path := filepath.Join(t.TempDir(), "failures.json")
	l := NewLimiter(Limits{PerSource: 2, PerSourceWindow: time.Hour, Global: 3, GlobalWindow: time.Hour}, path, clock)

	a1, _, _, ok := l.Begin("10.0.0.1")
	if !ok {
		t.Fatal("first attempt refused")
	}
	if _, _, busy, ok := l.Begin("10.0.0.1"); ok || !busy {
		t.Fatal("a second concurrent attempt from one source must be refused as busy")
	}
	l.Done(a1)
	a2, _, _, _ := l.Begin("10.0.0.1")
	l.Done(a2)
	l.Succeed(a2)
	if l.Failures() != 1 {
		t.Fatalf("success must refund only its own attempt, got %d", l.Failures())
	}

	reloaded := NewLimiter(l.limits, path, clock)
	if reloaded.Failures() != 1 {
		t.Fatal("failures did not survive a restart")
	}
	for _, src := range []string{"10.0.0.2", "10.0.0.3"} {
		a, _, _, ok := reloaded.Begin(src)
		if !ok {
			t.Fatalf("%s refused early", src)
		}
		reloaded.Done(a)
	}
	if _, retry, _, ok := reloaded.Begin("10.0.0.4"); ok || retry <= 0 {
		t.Fatal("global limit not enforced")
	}
	now = now.Add(time.Hour + time.Second)
	if _, _, _, ok := reloaded.Begin("10.0.0.4"); !ok {
		t.Fatal("window did not slide")
	}
}

func TestSourceKeyGroupsIPv6Slash64(t *testing.T) {
	a := SourceKey(netip.MustParseAddr("2001:db8:1:2::1"))
	b := SourceKey(netip.MustParseAddr("2001:db8:1:2:ffff::9"))
	if a != b || SourceKey(netip.MustParseAddr("::ffff:192.0.2.1")) != "192.0.2.1" {
		t.Fatalf("source keys: %s %s", a, b)
	}
}

func TestBadRequestsAreRefusedBeforeAnyGuess(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	for _, h := range []hello{
		{V: 2, Node: "n", Runtime: ops.RuntimeKubeadm, PAKE: make([]byte, msgALen)},
		{V: 1, Node: "Bad_Name", Runtime: ops.RuntimeKubeadm, PAKE: make([]byte, msgALen)},
		{V: 1, Node: "n", Runtime: ops.RuntimeKubeadm, PAKE: make([]byte, 3)},
	} {
		r := rawSession(t, ts.addr, h)
		if len(r) != 1 || r[0].Error != ErrCodeBadRequest {
			t.Fatalf("want bad-request, got %+v", r)
		}
	}
	r := rawSession(t, ts.addr, hello{V: 1, Node: "n", Runtime: ops.RuntimeK0s, PAKE: make([]byte, msgALen)})
	if len(r) != 1 || r[0].Error != ErrCodeRuntime {
		t.Fatalf("want runtime-mismatch, got %+v", r)
	}
	if ts.limiter.Failures() != 0 {
		t.Fatal("malformed requests were charged as guesses")
	}
}

func TestInvalidPAKEPointIsAChargedFailure(t *testing.T) {
	ts := startServer(t, goodPass, DefaultServerLimits)
	r := rawSession(t, ts.addr, hello{V: 1, Node: "n", Runtime: ops.RuntimeKubeadm, PAKE: make([]byte, msgALen)})
	if len(r) != 0 {
		t.Fatalf("identity point must get no PAKE reply, got %+v", r)
	}
	time.Sleep(50 * time.Millisecond)
	if ts.limiter.Failures() != 1 {
		t.Fatal("an invalid PAKE message must still be charged")
	}
}

func TestGrantTTL(t *testing.T) {
	g, _ := (&fakeMinter{}).Mint(context.Background(), "n")
	if err := g.Validate(); err != nil {
		t.Fatal(err)
	}
	for _, ttl := range []int{0, -1, int(ops.TokenTTL/time.Second) + 1, 86400} {
		g.TTLSeconds = ttl
		if g.Validate() == nil {
			t.Fatalf("ttl %d accepted", ttl)
		}
	}
}

func TestTamperedSealedPayloadIsRejected(t *testing.T) {
	k := keys{th: bytes.Repeat([]byte{1}, 32), aead: bytes.Repeat([]byte{2}, 32)}
	s, err := seal(k, []byte("payload"))
	if err != nil {
		t.Fatal(err)
	}
	s[len(s)-1] ^= 1
	if _, err := open(k, s); err == nil {
		t.Fatal("tampered payload opened")
	}
	k2 := k
	k2.th = bytes.Repeat([]byte{3}, 32)
	s[len(s)-1] ^= 1
	if _, err := open(k2, s); err == nil {
		t.Fatal("payload opened under another transcript")
	}
}

func honestClient(t *testing.T, c *tls.Conn, b binding, h *hello) keys {
	t.Helper()
	msgA, state, err := cpace.Start(goodPass, b.contextInfo())
	if err != nil {
		t.Fatal(err)
	}
	*h = hello{V: Version, Node: "node-1", Runtime: ops.RuntimeKubeadm, PAKE: msgA}
	if err := writeFrame(c, *h); err != nil {
		t.Fatal(err)
	}
	var r serverReply
	if err := readFrame(c, &r); err != nil {
		t.Fatal(err)
	}
	isk, err := state.Finish(r.PAKE)
	if err != nil {
		t.Fatal(err)
	}
	k, err := schedule(isk, b, *h, r.PAKE)
	if err != nil {
		t.Fatal(err)
	}
	return k
}

func TestNetworkFailureBeforeThePAKEReplyCostsNoGuess(t *testing.T) {
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer ln.Close()
	cert, _ := LoadOrCreateCert(t.TempDir())
	go func() {
		for {
			c, err := ln.Accept()
			if err != nil {
				return
			}
			tc := tls.Server(c, &tls.Config{Certificates: []tls.Certificate{cert}, MinVersion: tls.VersionTLS13})
			_ = tc.Handshake()
			var h hello
			_ = readFrame(tc, &h)
			tc.Close()
		}
	}()
	budget := NewClientBudget(1, time.Hour, nil)
	for i := 0; i < 3; i++ {
		cl := client(goodPass)
		cl.Budget = budget
		_, err := cl.Join(context.Background(), netip.MustParseAddrPort(ln.Addr().String()))
		var be *ErrBudget
		if err == nil || errors.As(err, &be) {
			t.Fatalf("attempt %d: want a network error, got %v", i, err)
		}
	}
}

func TestLimiterReportsRateLimitBeforeBusy(t *testing.T) {
	now := time.Unix(1_000_000, 0)
	l := NewLimiter(Limits{PerSource: 1, PerSourceWindow: time.Hour, Global: 10, GlobalWindow: time.Hour},
		filepath.Join(t.TempDir(), "failures.json"), func() time.Time { return now })
	if _, _, _, ok := l.Begin("10.0.0.1"); !ok {
		t.Fatal("first attempt refused")
	}
	// The first connection is still in progress (no Done yet) and has used
	// the source's only guess: the answer is rate-limited, not busy.
	_, retry, busy, ok := l.Begin("10.0.0.1")
	if ok || busy || retry <= 0 {
		t.Fatalf("want rate-limited with a delay, got ok=%v busy=%v retry=%v", ok, busy, retry)
	}
}
