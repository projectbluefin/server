package main

import (
	"crypto/ed25519"
	"crypto/rand"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"math/big"
	"os"
	"path/filepath"
	"testing"
	"time"
)

func testClusterCA(t *testing.T) ([]byte, string) {
	t.Helper()
	pub, key, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	template := &x509.Certificate{SerialNumber: big.NewInt(1), Subject: pkix.Name{CommonName: "cluster"}, NotBefore: time.Now().Add(-time.Hour), NotAfter: time.Now().Add(time.Hour), IsCA: true, BasicConstraintsValid: true, KeyUsage: x509.KeyUsageCertSign}
	der, err := x509.CreateCertificate(rand.Reader, template, template, pub, key)
	if err != nil {
		t.Fatal(err)
	}
	body := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: der})
	hash, err := certificateDiscoveryHash(body)
	if err != nil {
		t.Fatal(err)
	}
	return body, hash
}
func TestPartialJoinResumesOnlyMatchingCAAndDurableCluster(t *testing.T) {
	ca, hash := testClusterCA(t)
	e := Engine{Root: t.TempDir(), State: State{Role: "worker", ClusterID: "cluster"}}
	path := e.path("/etc/kubernetes/pki/ca.crt")
	os.MkdirAll(filepath.Dir(path), 0700)
	os.WriteFile(path, ca, 0600)
	join := Join{ClusterID: "cluster", CAHash: hash}
	partial, err := e.validatePartialJoin(join)
	if err != nil || !partial {
		t.Fatal("legitimate interrupted CA join cannot resume", err)
	}
	join.ClusterID = "different"
	if _, err = e.validatePartialJoin(join); err == nil {
		t.Fatal("different cluster replaced partial state")
	}
	join.ClusterID = "cluster"
	_, wrong := testClusterCA(t)
	join.CAHash = wrong
	if _, err = e.validatePartialJoin(join); err == nil {
		t.Fatal("mismatched CA replaced partial trust")
	}
	join.CAHash = hash
	identity := e.path("/var/lib/kubelet/pki/kubelet-client-current.pem")
	os.MkdirAll(filepath.Dir(identity), 0700)
	os.WriteFile(identity, []byte("already issued client authority"), 0600)
	if _, err = e.validatePartialJoin(join); err == nil {
		t.Fatal("registered client identity overwritten because kubelet.conf missing")
	}
}
