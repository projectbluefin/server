package main

import (
	"bufio"
	"context"
	"crypto/x509"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"net"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"
)

func now() time.Time { return time.Now().UTC() }
func parseCertificate(b []byte) (*x509.Certificate, error) {
	p, _ := pem.Decode(b)
	if p == nil || p.Type != "CERTIFICATE" {
		return nil, errors.New("invalid_cluster_ca")
	}
	return x509.ParseCertificate(p.Bytes)
}
func main() {
	profile, err := os.ReadFile("/etc/bluefin/server/profile")
	if errors.Is(err, os.ErrNotExist) || (err == nil && strings.TrimSpace(string(profile)) != "complete") {
		return
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "profile_unavailable")
		os.Exit(1)
	}
	if os.Geteuid() != 0 {
		fmt.Fprintln(os.Stderr, "root_service_required")
		os.Exit(1)
	}
	if len(os.Args) == 2 && os.Args[1] == "physical" {
		physical()
		return
	}
	if len(os.Args) != 1 {
		fmt.Fprintln(os.Stderr, "invalid_argument")
		os.Exit(2)
	}
	if err := os.MkdirAll("/run/bluefin-server", 0750); err != nil {
		os.Exit(1)
	}
	// Hold one daemon owner, including across systemd restart and Unix socket recreation.
	lock, err := os.OpenFile("/run/bluefin-server/bootstrap.lock", os.O_CREATE|os.O_RDWR, 0600)
	if err != nil {
		os.Exit(1)
	}
	defer lock.Close()
	if err = syscall.Flock(int(lock.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		fmt.Fprintln(os.Stderr, "bootstrap_already_running")
		os.Exit(1)
	}
	e := &Engine{}
	if err := e.prepareStateDirectories(); err != nil {
		fmt.Fprintln(os.Stderr, "unsafe_server_state_directory")
		os.Exit(1)
	}
	if err := e.load(); err != nil {
		fmt.Fprintln(os.Stderr, err.Error())
		os.Exit(1)
	}
	var pending *Runtime
	if e.State.Upgrade != nil {
		pending = &e.State.Upgrade.Target
	}
	if err := e.protectReleases(pending); err != nil {
		e.fail("release_protection_failed")
		os.Exit(1)
	}
	if err := e.enableServerUpdates(); err != nil {
		e.fail("server_update_opt_in_failed")
		os.Exit(1)
	}
	if e.State.Role != "unassigned" && e.State.Phase == "ready" {
		e.State.Phase = "verifying"
		e.State.Revision++
		if err := e.persist(); err != nil {
			os.Exit(1)
		}
	}
	if err := run("systemd-tmpfiles", "--create", "bluefin-server-runtime.conf"); err != nil {
		e.fail(err.Error())
		fmt.Fprintln(os.Stderr, err.Error())
		os.Exit(1)
	}
	socket := "/run/bluefin-server/bootstrap.sock"
	os.Remove(socket)
	listener, err := net.Listen("unix", socket)
	if err != nil {
		os.Exit(1)
	}
	defer listener.Close()
	if err = os.Chmod(socket, 0600); err != nil {
		os.Exit(1)
	}
	server := &http.Server{Handler: http.HandlerFunc(e.serveHTTP), ConnContext: unixPeer, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 30 * time.Second, WriteTimeout: 15 * time.Minute, IdleTimeout: 30 * time.Second}
	go e.resume()
	go func() {
		signals := make(chan os.Signal, 1)
		signal.Notify(signals, syscall.SIGTERM, syscall.SIGINT)
		<-signals
		ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
		defer cancel()
		_ = server.Shutdown(ctx)
	}()
	if err = server.Serve(listener); err != nil && err != http.ErrServerClosed {
		fmt.Fprintln(os.Stderr, "bootstrap_socket_failed")
		os.Exit(1)
	}
}
func physical() {
	// Lifecycle controls stay on the private physical terminal, never a LAN UI.
	if st, err := os.Stdout.Stat(); err != nil || st.Mode()&os.ModeCharDevice == 0 {
		fmt.Fprintln(os.Stderr, "private_terminal_required")
		os.Exit(1)
	}
	if st, err := os.Stdin.Stat(); err != nil || st.Mode()&os.ModeCharDevice == 0 {
		os.Exit(1)
	}
	scanner := bufio.NewScanner(os.Stdin)
	for {
		fmt.Print("\nBluefin Server: status | resume\n> ")
		if !scanner.Scan() {
			return
		}
		action := strings.TrimSpace(scanner.Text())
		switch action {
		case "status":
			var s State
			body, err := os.ReadFile("/var/lib/bluefin/server/state.json")
			if err != nil || json.Unmarshal(body, &s) != nil {
				fmt.Println("Status unavailable")
				continue
			}
			fmt.Printf("Profile: %s  Role: %s  Phase: %s\n", s.Profile, s.Role, s.Phase)
			if s.Error != "" {
				fmt.Printf("Error: %s\n", s.Error)
			}
			if s.ConsoleStatus == "awaiting_oauth" {
				fmt.Println("Console awaiting OAuth")
			} else if s.ConsoleStatus != "" {
				fmt.Printf("Console: %s (cluster-internal)\n", s.ConsoleStatus)
			}
			if s.Role == "unassigned" {
				e := Engine{State: s}
				if err := e.requireUninitializedHost(); err != nil {
					fmt.Printf("Preserved-state blocker: %s\n", err.Error())
				}
			}
			if s.PendingWorkers != nil {
				fmt.Printf("Worker runtime updates: manual per node, target %s\n", s.PendingWorkers.ImageVersion)
			}
		case "resume":
			if err := run("systemctl", "restart", "bluefin-server-bootstrap.service"); err != nil {
				fmt.Println("Resume failed; preserved cluster state requires operator diagnosis")
			} else {
				fmt.Println("Resume requested; no reset or reinstall performed")
			}
		default:
			fmt.Println("Unknown command")
		}
	}
}
