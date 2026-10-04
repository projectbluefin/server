package join

import (
	"encoding/json"
	"net/netip"
	"os"
	"sync"
	"time"
)

// Limits bound password guesses: every PAKE run is a guess, charged before
// the PAKE starts and refunded only when the peer proved the passphrase.
type Limits struct {
	PerSource       int
	PerSourceWindow time.Duration
	Global          int
	GlobalWindow    time.Duration
}

var DefaultServerLimits = Limits{PerSource: 5, PerSourceWindow: 15 * time.Minute, Global: 20, GlobalWindow: time.Hour}

// Limiter is the server's guess accounting. The failure log persists in
// path (if set), so restarting the service does not reset it.
type Limiter struct {
	limits Limits
	path   string
	now    func() time.Time

	mu     sync.Mutex
	failed []failure
	active map[string]bool
	seq    uint64
}

type failure struct {
	Source string    `json:"source"`
	At     time.Time `json:"at"`
	id     uint64
}

// Attempt is one charged guess.
type Attempt struct {
	source string
	id     uint64
}

func NewLimiter(limits Limits, path string, now func() time.Time) *Limiter {
	if now == nil {
		now = time.Now
	}
	l := &Limiter{limits: limits, path: path, now: now, active: map[string]bool{}}
	if path != "" {
		if data, err := os.ReadFile(path); err == nil {
			_ = json.Unmarshal(data, &l.failed)
		}
	}
	return l
}

// SourceKey groups addresses an attacker can trivially vary: an IPv6 /64,
// or one IPv4 address.
func SourceKey(a netip.Addr) string {
	a = a.Unmap().WithZone("")
	if a.Is6() {
		p, _ := a.Prefix(64)
		return p.String()
	}
	return a.String()
}

func (l *Limiter) prune(now time.Time) {
	keep := l.failed[:0]
	horizon := max(l.limits.GlobalWindow, l.limits.PerSourceWindow)
	for _, f := range l.failed {
		if now.Sub(f.At) < horizon {
			keep = append(keep, f)
		}
	}
	l.failed = keep
}

// Begin charges one guess for source, atomically with the limit check. It
// returns ok=false with a retry delay when a limit is reached or the
// source already has a connection in progress. Limits are checked first:
// a source over its budget is told so even while its previous connection
// is still being torn down.
func (l *Limiter) Begin(source string) (a *Attempt, retryAfter time.Duration, busy, ok bool) {
	l.mu.Lock()
	defer l.mu.Unlock()
	now := l.now()
	l.prune(now)
	var global, mine int
	var oldestGlobal, oldestMine time.Time
	for _, f := range l.failed {
		if now.Sub(f.At) < l.limits.GlobalWindow {
			if global == 0 {
				oldestGlobal = f.At
			}
			global++
		}
		if f.Source == source && now.Sub(f.At) < l.limits.PerSourceWindow {
			if mine == 0 {
				oldestMine = f.At
			}
			mine++
		}
	}
	switch {
	case mine >= l.limits.PerSource:
		return nil, oldestMine.Add(l.limits.PerSourceWindow).Sub(now), false, false
	case global >= l.limits.Global:
		return nil, oldestGlobal.Add(l.limits.GlobalWindow).Sub(now), false, false
	}
	if l.active[source] {
		return nil, time.Second, true, false
	}
	l.seq++
	l.failed = append(l.failed, failure{Source: source, At: now, id: l.seq})
	l.active[source] = true
	l.save()
	return &Attempt{source: source, id: l.seq}, 0, false, true
}

// Succeed refunds exactly this attempt's charge.
func (l *Limiter) Succeed(a *Attempt) {
	l.mu.Lock()
	defer l.mu.Unlock()
	for i, f := range l.failed {
		if f.id == a.id && f.Source == a.source {
			l.failed = append(l.failed[:i], l.failed[i+1:]...)
			break
		}
	}
	l.save()
}

// Done ends the attempt's connection.
func (l *Limiter) Done(a *Attempt) {
	l.mu.Lock()
	defer l.mu.Unlock()
	delete(l.active, a.source)
}

// Failures counts charged guesses in the global window.
func (l *Limiter) Failures() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.prune(l.now())
	return len(l.failed)
}

// inUse reports whether source currently holds a connection slot. It is a
// test seam: a replay opened from the same source right after an honest
// exchange must wait for the slot to be released instead of being rejected
// as busy while the previous handler is still running. See issue #391.
func (l *Limiter) inUse(source string) bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.active[source]
}

func (l *Limiter) save() {
	if l.path == "" {
		return
	}
	data, err := json.Marshal(l.failed)
	if err != nil {
		return
	}
	tmp := l.path + ".tmp"
	if os.WriteFile(tmp, data, 0o600) == nil {
		_ = os.Rename(tmp, l.path)
	}
}

// MintLimiter caps successful token mints (each is a kube-system Secret).
type MintLimiter struct {
	max    int
	window time.Duration
	now    func() time.Time
	mu     sync.Mutex
	times  []time.Time
}

func NewMintLimiter(max int, window time.Duration, now func() time.Time) *MintLimiter {
	if now == nil {
		now = time.Now
	}
	return &MintLimiter{max: max, window: window, now: now}
}

func (m *MintLimiter) Allow() bool {
	m.mu.Lock()
	defer m.mu.Unlock()
	now := m.now()
	keep := m.times[:0]
	for _, t := range m.times {
		if now.Sub(t) < m.window {
			keep = append(keep, t)
		}
	}
	m.times = keep
	if len(m.times) >= m.max {
		return false
	}
	m.times = append(m.times, now)
	return true
}

// ClientBudget is the node's guess accounting across every control plane
// candidate it tries, so a rogue mDNS advertiser publishing many instances
// gets no more guesses than one would.
type ClientBudget struct {
	Max    int
	Window time.Duration
	now    func() time.Time
	mu     sync.Mutex
	failed []time.Time
}

func NewClientBudget(max int, window time.Duration, now func() time.Time) *ClientBudget {
	if now == nil {
		now = time.Now
	}
	return &ClientBudget{Max: max, Window: window, now: now}
}

// Take charges one guess or says how long to wait.
func (b *ClientBudget) Take() (time.Duration, bool) {
	b.mu.Lock()
	defer b.mu.Unlock()
	now := b.now()
	keep := b.failed[:0]
	for _, t := range b.failed {
		if now.Sub(t) < b.Window {
			keep = append(keep, t)
		}
	}
	b.failed = keep
	if len(b.failed) >= b.Max {
		return b.failed[0].Add(b.Window).Sub(now), false
	}
	b.failed = append(b.failed, now)
	return 0, true
}

// Refund returns the last charge after the server proved the passphrase.
func (b *ClientBudget) Refund() {
	b.mu.Lock()
	defer b.mu.Unlock()
	if n := len(b.failed); n > 0 {
		b.failed = b.failed[:n-1]
	}
}
