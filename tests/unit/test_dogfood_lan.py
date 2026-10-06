"""scripts/dogfood-lan.sh: the host-side L2 segment the multi-VM QEMU checks
(dogfood-mdns, dogfood-homelab-cluster, -installer, -templates) share.

None of those checks runs in CI, and none of them can tell a broken switch
from a guest that never came up: both end in a probe timeout. These tests run
the real lan_start/lan_stop with a stub QEMU and talk to the learning switch
over TCP the way QEMU's stream netdev does (4-byte big-endian length, then
the Ethernet frame).
"""

from __future__ import annotations

import os
import shlex
import socket
import struct
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LAN = ROOT / "scripts" / "dogfood-lan.sh"

BROADCAST = b"\xff" * 6
MAC_A = bytes.fromhex("525400b10011")
MAC_B = bytes.fromhex("525400b10012")
MAC_C = bytes.fromhex("525400b10013")
MAC_GONE = bytes.fromhex("525400b100ee")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def frame(dst: bytes, src: bytes, payload: bytes) -> bytes:
    eth = dst + src + b"\x88\xb5" + payload
    return struct.pack(">I", len(eth)) + eth


def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("switch closed the port")
        buf += chunk
    return buf


def recv_frame(sock: socket.socket, timeout: float = 5.0) -> bytes:
    sock.settimeout(timeout)
    (length,) = struct.unpack(">I", recv_exact(sock, 4))
    return recv_exact(sock, length)


def nothing_arrives(sock: socket.socket, wait: float = 0.5) -> bool:
    sock.settimeout(wait)
    try:
        data = sock.recv(1)
    except TimeoutError:
        return True
    return data == b""


class Lan:
    """lan_start in a bash that stays up until stop() runs lan_stop."""

    def __init__(self, tmp_path: Path, env: dict[str, str] | None = None) -> None:
        self.state = tmp_path / "state"
        self.state.mkdir()
        self.port = free_port()
        stub_bin = tmp_path / "bin"
        stub_bin.mkdir()
        self.qemu_args = tmp_path / "qemu.args"
        self.unshare_args = tmp_path / "unshare.args"
        # The router is a QEMU with no machine; record its argv and idle.
        for name, record in (("qemu-system-x86_64", self.qemu_args), ("unshare", self.unshare_args)):
            stub = stub_bin / name
            stub.write_text(
                "#!/bin/bash\n"
                f'printf "%s\\n" "$@" > {shlex.quote(str(record))}\n'
                "exec sleep 300\n",
                encoding="utf-8",
            )
            stub.chmod(0o755)
        script = (
            f". {shlex.quote(str(LAN))}\n"
            'lan_start "$1" "$2"\n'
            'printf "ready %s %s\\n" "${switch_pid}" "${router_pid}"\n'
            'printf "nic %s\\n" "$(nic 11)"\n'
            "read -r _\n"
            "lan_stop\n"
            "wait\n"
        )
        self.proc = subprocess.Popen(
            ["bash", "-c", script, "lan", str(self.state), str(self.port)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            env={"PATH": f"{stub_bin}:{os.environ['PATH']}", **(env or {})},
        )
        assert self.proc.stdout
        ready = self.proc.stdout.readline().split()
        assert ready[:1] == ["ready"], ready
        self.switch_pid, self.router_pid = int(ready[1]), int(ready[2])
        self.nic = self.proc.stdout.readline().removeprefix("nic ").strip()
        self.socks: list[socket.socket] = []

    def connect(self, rcvbuf: int | None = None) -> socket.socket:
        sock = socket.socket()
        if rcvbuf is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, rcvbuf)
        sock.connect(("127.0.0.1", self.port))
        self.socks.append(sock)
        return sock

    def wait_for_args(self, path: Path) -> list[str]:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if path.exists() and path.read_text(encoding="utf-8"):
                return path.read_text(encoding="utf-8").splitlines()
            time.sleep(0.05)
        raise AssertionError(f"{path.name}: the router was never started")

    def stop(self) -> int:
        for sock in self.socks:
            sock.close()
        if self.proc.poll() is None:
            assert self.proc.stdin
            self.proc.stdin.write("\n")
            self.proc.stdin.flush()
        return self.proc.wait(timeout=10)


@pytest.fixture
def lan(tmp_path: Path) -> Iterator[Lan]:
    segment = Lan(tmp_path)
    try:
        yield segment
    finally:
        segment.stop()


def ports(lan: Lan, *macs: bytes) -> list[socket.socket]:
    """One connected port per MAC; each announces itself so the switch
    learns it, and every port drains those announcements."""
    socks = [lan.connect() for _ in macs]
    time.sleep(0.2)
    for sock, mac in zip(socks, macs, strict=True):
        sock.sendall(frame(BROADCAST, mac, b"hello"))
        for other in socks:
            if other is not sock:
                assert recv_frame(other)[6:12] == mac
    return socks


def test_broadcast_floods_every_other_port_but_not_the_sender(lan: Lan) -> None:
    a, b, c = ports(lan, MAC_A, MAC_B, MAC_C)
    a.sendall(frame(BROADCAST, MAC_A, b"who-has"))
    assert recv_frame(b)[14:] == b"who-has"
    assert recv_frame(c)[14:] == b"who-has"
    assert nothing_arrives(a), "a frame must never come back to its sender"


def test_multicast_floods_like_broadcast(lan: Lan) -> None:
    # mDNS goes to 01:00:5e:00:00:fb: the group bit, not an all-ones address.
    a, b, c = ports(lan, MAC_A, MAC_B, MAC_C)
    mdns = bytes.fromhex("01005e0000fb")
    a.sendall(frame(mdns, MAC_A, b"mdns"))
    assert recv_frame(b)[14:] == b"mdns"
    assert recv_frame(c)[14:] == b"mdns"
    assert nothing_arrives(a)


def test_unicast_to_a_learned_mac_goes_to_its_port_only(lan: Lan) -> None:
    a, b, c = ports(lan, MAC_A, MAC_B, MAC_C)
    a.sendall(frame(MAC_C, MAC_A, b"to-c"))
    got = recv_frame(c)
    assert got[0:6] == MAC_C and got[6:12] == MAC_A and got[14:] == b"to-c"
    assert nothing_arrives(b), "a learned unicast frame must not be flooded"
    assert nothing_arrives(a)


def test_unicast_to_an_unknown_mac_is_flooded(lan: Lan) -> None:
    a, b, c = ports(lan, MAC_A, MAC_B, MAC_C)
    a.sendall(frame(MAC_GONE, MAC_A, b"unknown"))
    assert recv_frame(b)[14:] == b"unknown"
    assert recv_frame(c)[14:] == b"unknown"
    assert nothing_arrives(a)


def test_a_mac_that_moves_is_relearned(lan: Lan) -> None:
    a, b, c = ports(lan, MAC_A, MAC_B, MAC_C)
    # MAC_B now speaks from c's port (a guest reconnecting on a new stream).
    c.sendall(frame(MAC_A, MAC_B, b"moved"))
    assert recv_frame(a)[14:] == b"moved"
    a.sendall(frame(MAC_B, MAC_A, b"reply"))
    assert recv_frame(c)[14:] == b"reply"
    assert nothing_arrives(b)


def test_a_closed_port_is_forgotten_and_its_mac_is_flooded(lan: Lan) -> None:
    a, b, c = ports(lan, MAC_A, MAC_B, MAC_C)
    b.close()
    time.sleep(0.3)
    a.sendall(frame(MAC_B, MAC_A, b"after-close"))
    assert recv_frame(c)[14:] == b"after-close", "a MAC on a closed port must be flooded, not sent nowhere"
    # The switch keeps serving the remaining ports.
    c.sendall(frame(MAC_A, MAC_C, b"still-up"))
    assert recv_frame(a)[14:] == b"still-up"


def test_frames_split_across_writes_are_reassembled(lan: Lan) -> None:
    a, b = ports(lan, MAC_A, MAC_B)
    payload = bytes(range(256)) * 6
    data = frame(MAC_B, MAC_A, payload)
    for i in range(0, len(data), 7):
        a.sendall(data[i:i + 7])
        time.sleep(0.001)
    assert recv_frame(b)[14:] == payload


def test_back_to_back_frames_in_one_write_are_all_delivered(lan: Lan) -> None:
    a, b = ports(lan, MAC_A, MAC_B)
    a.sendall(b"".join(frame(MAC_B, MAC_A, f"n{i}".encode()) for i in range(50)))
    assert [recv_frame(b)[14:] for _ in range(50)] == [f"n{i}".encode() for i in range(50)]


def test_a_port_that_does_not_read_loses_frames_instead_of_stalling(lan: Lan) -> None:
    a, b = ports(lan, MAC_A, MAC_B)
    # A guest still in firmware: connected, never reading.
    stuck = lan.connect(rcvbuf=4096)
    time.sleep(0.2)
    chunk = 64 * 1024
    count = 512  # 32 MiB, far past the switch's 1 MiB per-port buffer
    for i in range(count):
        a.sendall(frame(BROADCAST, MAC_A, i.to_bytes(4, "big") + bytes(chunk)))
        recv_frame(b, timeout=10)
    # The reading port still gets unicast promptly.
    a.sendall(frame(MAC_B, MAC_A, b"after-flood"))
    assert recv_frame(b)[14:] == b"after-flood"
    # Whatever reached the stuck port is bounded and well framed.
    seen = 0
    stuck.settimeout(1)
    try:
        while True:
            got = recv_frame(stuck, timeout=1)
            assert got[6:12] == MAC_A
            seen += 1
    except TimeoutError:
        pass
    assert seen < count // 2, f"stuck port got {seen} of {count} frames: the switch is buffering without bound"


def test_router_joins_the_segment_through_a_hub(lan: Lan) -> None:
    args = lan.wait_for_args(lan.qemu_args)
    stream = f"stream,id=sw,server=off,reconnect-ms=1000,addr.type=inet,addr.host=127.0.0.1,addr.port={lan.port}"
    assert args[:6] == ["-machine", "none", "-nodefaults", "-display", "none", "-monitor"]
    pairs = [args[i + 1] for i, a in enumerate(args) if a == "-netdev"]
    assert pairs == [
        "user,id=u0",
        "hubport,id=hu,hubid=0,netdev=u0",
        stream,
        "hubport,id=hs,hubid=0,netdev=sw",
    ]
    assert not lan.unshare_args.exists(), "no DOGFOOD_DNS: the router runs without a private mount namespace"


def test_nic_puts_a_guest_on_the_segment(lan: Lan) -> None:
    assert lan.nic == (
        f"-netdev stream,id=sw,server=off,reconnect-ms=1000,addr.type=inet,addr.host=127.0.0.1,addr.port={lan.port}"
        " -device virtio-net-pci,netdev=sw,mac=52:54:00:b1:00:11"
    )


def test_dogfood_dns_gives_the_router_its_own_resolv_conf(tmp_path: Path) -> None:
    segment = Lan(tmp_path, env={"DOGFOOD_DNS": "192.0.2.53"})
    try:
        args = segment.wait_for_args(segment.unshare_args)
        assert (segment.state / "router-resolv.conf").read_text(encoding="utf-8") == "nameserver 192.0.2.53\n"
        assert args[:3] == ["-rm", "sh", "-c"]
        assert args[3] == 'mount --bind "$0" /etc/resolv.conf && exec "$@"'
        assert args[4] == str(segment.state / "router-resolv.conf")
        assert args[5] == "qemu-system-x86_64"
        assert "hubport,id=hs,hubid=0,netdev=sw" in args
        assert not segment.qemu_args.exists(), "the stub unshare never execs QEMU"
    finally:
        assert segment.stop() == 0


def test_lan_stop_stops_the_switch_and_the_router(tmp_path: Path) -> None:
    segment = Lan(tmp_path)
    with socket.create_connection(("127.0.0.1", segment.port)) as sock:
        segment.wait_for_args(segment.qemu_args)
        assert segment.stop() == 0
        for pid in (segment.switch_pid, segment.router_pid):
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
        sock.settimeout(2)
        # FIN if the switch had accepted the port, RST if it was still queued.
        try:
            assert sock.recv(1) == b"", "the switch must close its ports when it stops"
        except ConnectionResetError:
            pass
    with socket.socket() as probe, pytest.raises(ConnectionRefusedError):
        probe.connect(("127.0.0.1", segment.port))


def test_lan_stop_is_safe_before_lan_start() -> None:
    result = subprocess.run(["bash", "-c", f". {shlex.quote(str(LAN))}; lan_stop"],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
