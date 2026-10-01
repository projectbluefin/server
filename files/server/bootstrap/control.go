package main

import (
	"context"
	"encoding/json"
	"net"
	"net/http"
	"syscall"
	"time"
)

type peerKey struct{}

func unixPeer(ctx context.Context, c net.Conn) context.Context {
	uid := uint32(0xffffffff)
	if u, ok := c.(*net.UnixConn); ok {
		raw, err := u.SyscallConn()
		if err == nil {
			_ = raw.Control(func(fd uintptr) {
				cred, e := syscall.GetsockoptUcred(int(fd), syscall.SOL_SOCKET, syscall.SO_PEERCRED)
				if e == nil {
					uid = cred.Uid
				}
			})
		}
	}
	return context.WithValue(ctx, peerKey{}, uid)
}
func respond(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func (e *Engine) serveHTTP(w http.ResponseWriter, r *http.Request) {
	uid, known := r.Context().Value(peerKey{}).(uint32)
	if !known || uid != 0 {
		respond(w, 403, map[string]string{"error": "peer_forbidden"})
		return
	}
	if r.URL.Path == "/v1/status" && r.Method == http.MethodGet {
		e.mu.Lock()
		status := e.State.status()
		e.mu.Unlock()
		respond(w, 200, status)
		return
	}
	if r.Method != http.MethodPost {
		respond(w, 405, map[string]string{"error": "method_not_allowed"})
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, 65536)
	switch r.URL.Path {
	case "/v1/initialize":
		var req RevisionRequest
		if decodeJSON(r.Body, &req) != nil {
			respond(w, 400, map[string]string{"error": "invalid_request"})
			return
		}
		e.mu.Lock()
		action := e.State.initializeAction()
		if e.busy || action == "" || req.ExpectedRevision != e.State.Revision {
			e.mu.Unlock()
			respond(w, 409, map[string]string{"error": "not_ready_or_stale"})
			return
		}
		// The only action reachable here is "resume": load() commits an
		// unassigned host's role before the socket is served, so a fresh host
		// never reaches /v1/initialize unassigned.
		candidate := e.State
		candidate.Phase = "pending"
		candidate.Error = ""
		candidate.Revision++
		err := saveJSON(e.path("/var/lib/bluefin/server/state.json"), candidate)
		if err == nil {
			e.State = candidate
		}
		e.mu.Unlock()
		if err != nil {
			respond(w, 409, map[string]string{"error": err.Error()})
			return
		}
		respond(w, 202, map[string]string{"phase": "pending"})
		go e.resume()
	case "/v1/join":
		var req struct {
			ExpectedRevision uint64 `json:"expected_revision"`
			Join             Join   `json:"join"`
		}
		if decodeJSON(r.Body, &req) != nil {
			respond(w, 400, map[string]string{"error": "invalid_request"})
			return
		}
		if err := req.Join.validate(time.Now()); err != nil {
			respond(w, 400, map[string]string{"error": err.Error()})
			return
		}
		e.mu.Lock()
		candidate := e.State
		action := candidate.joinAction(req.Join.ClusterID, e.hasWorkerIdentity())
		if e.busy || action == "" || req.ExpectedRevision != candidate.Revision {
			e.mu.Unlock()
			respond(w, 409, map[string]string{"error": "enrollment_not_allowed_or_stale"})
			return
		}
		var err error
		if action == "renew" {
			if _, err = e.validatePartialJoin(req.Join); err != nil {
				e.mu.Unlock()
				respond(w, 409, map[string]string{"error": err.Error()})
				return
			}
		}
		if action == "start" {
			if err = e.requireUninitializedHost(); err != nil {
				e.mu.Unlock()
				respond(w, 409, map[string]string{"error": err.Error()})
				return
			}
			err = candidate.commitRole("worker", req.ExpectedRevision)
		} else {
			candidate.Phase = "pending"
			candidate.Error = ""
			candidate.Revision++
		}
		if err == nil {
			err = saveJSON(e.path("/var/lib/bluefin/server/private-join.json"), req.Join)
		}
		if err == nil {
			candidate.ClusterID = req.Join.ClusterID
			candidate.ClusterCAHash = req.Join.CAHash
			err = saveJSON(e.path("/var/lib/bluefin/server/state.json"), candidate)
			if err == nil {
				e.State = candidate
			}
		}
		e.mu.Unlock()
		if err != nil {
			respond(w, 409, map[string]string{"error": err.Error()})
			return
		}
		respond(w, 202, map[string]string{"phase": "pending"})
		go e.resume()
	case "/v1/upgrade":
		var req struct {
			ExpectedRevision uint64 `json:"expected_revision"`
			ImageVersion     string `json:"image_version"`
		}
		if decodeJSON(r.Body, &req) != nil || !safeVersion.MatchString(req.ImageVersion) {
			respond(w, 400, map[string]string{"error": "invalid_request"})
			return
		}
		e.mu.Lock()
		action := e.State.upgradeAction(req.ImageVersion)
		if e.busy || action == "" || req.ExpectedRevision != e.State.Revision {
			e.mu.Unlock()
			respond(w, 409, map[string]string{"error": "not_ready_or_stale"})
			return
		}
		if action == "resume" {
			e.State.Phase = "upgrade_pending"
		} else {
			e.State.Upgrade = &Transaction{Target: Runtime{ImageVersion: req.ImageVersion}, Stage: "verify_payloads", StartedAt: now()}
			e.State.Phase = "upgrade_verifying"
		}
		e.State.Error = ""
		e.State.Revision++
		err := e.persist()
		e.mu.Unlock()
		if err != nil {
			respond(w, 503, map[string]string{"error": "upgrade_state_write_failed"})
			return
		}
		respond(w, 202, map[string]string{"phase": "upgrade_pending"})
		go e.resume()
	default:
		respond(w, 404, map[string]string{"error": "unknown_action"})
	}
}
