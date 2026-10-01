package main

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestControlRejectsUnknownPeerAndUnrelatedHostUID(t *testing.T) {
	e := Engine{State: State{Profile: "complete", Role: "unassigned", Revision: 1}}
	for _, uid := range []any{nil, uint32(1000), uint32(1001)} {
		r := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
		if uid != nil {
			r = r.WithContext(context.WithValue(r.Context(), peerKey{}, uid))
		}
		w := httptest.NewRecorder()
		e.serveHTTP(w, r)
		if w.Code != 403 {
			t.Fatalf("unexpected status %d", w.Code)
		}
	}
}
func TestMalformedJoinDoesNotSelectWorkerOrInitialize(t *testing.T) {
	e := Engine{Root: t.TempDir(), State: State{Schema: 1, Profile: "complete", Role: "unassigned", Phase: "awaiting_owner", Revision: 1}}
	body := `{"expected_revision":1,"join":{"api_endpoint":"192.168.1.2:6443","token":"abcdef.0123456789abcdef","ca_hash":"unsafe-skip-ca","expires_at":"2020-01-01T00:00:00Z","cluster_id":"cluster"}}`
	r := httptest.NewRequest(http.MethodPost, "/v1/join", strings.NewReader(body))
	r = r.WithContext(context.WithValue(r.Context(), peerKey{}, uint32(0)))
	w := httptest.NewRecorder()
	e.serveHTTP(w, r)
	if w.Code != 400 || e.State.Role != "unassigned" || e.State.Phase != "awaiting_owner" || e.State.Revision != 1 {
		t.Fatalf("malformed enrollment changed node: %d %+v", w.Code, e.State)
	}
}
