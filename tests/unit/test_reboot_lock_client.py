"""Executed coverage for bluefin-reboot-lock, the FleetLock client
(bluefin-host; elements/bluefin-server/os-host.bst).

A local HTTP server stands in for the FleetLock server: it records every
request and answers with the status, body and headers a test sets.
systemd-id128 is a stub on PATH.
"""


import base64
import json
import os
import socket
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ID = "0123456789abcdef0123456789abcdef"


class FleetLock(ThreadingHTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests: list[dict] = []
        self.code = 200
        self.body = b""
        self.headers: dict[str, str] = {}

    @property
    def base(self) -> str:
        return f"127.0.0.1:{self.server_address[1]}"


class Handler(BaseHTTPRequestHandler):
    server: FleetLock

    def do_POST(self) -> None:  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length", 0))
        self.server.requests.append(
            {"path": self.path, "headers": dict(self.headers), "body": self.rfile.read(length).decode()}
        )
        self.send_response(self.server.code)
        for k, v in self.server.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(self.server.body)))
        self.end_headers()
        self.wfile.write(self.server.body)

    def log_message(self, *args) -> None:
        pass


@pytest.fixture()
def server():
    httpd = FleetLock()
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def closed_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Lock:
    def __init__(self, tmp: Path, host_bin: Path) -> None:
        self.conf = tmp / "reboot-lock.conf"
        self.creds = tmp / "credentials"
        self.creds.mkdir()
        self.stubs = tmp / "bin"
        self.stubs.mkdir()
        self.id128(f"[ \"$1\" = machine-id ] && case \"$2\" in --app-specific=*) ;; *) exit 1 ;; esac || exit 1\necho {ID}\n")
        self.client = host_bin / "bluefin-reboot-lock"

    def id128(self, body: str) -> None:
        stub = self.stubs / "systemd-id128"
        stub.write_text("#!/bin/sh\n" + body, encoding="utf-8")
        stub.chmod(stub.stat().st_mode | stat.S_IXUSR)

    def configure(self, text: str) -> None:
        self.conf.write_text(text, encoding="utf-8")

    def __call__(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = dict(
            os.environ,
            PATH=f"{self.stubs}:{os.environ['PATH']}",
            BLUEFIN_REBOOT_LOCK_CONF=str(self.conf),
            CREDENTIALS_DIRECTORY=str(self.creds),
        )
        for proxy in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"):
            env.pop(proxy, None)
        result = subprocess.run([str(self.client), *args], capture_output=True, text=True, env=env, timeout=60)
        result.output = result.stdout + result.stderr  # type: ignore[attr-defined]
        return result


@pytest.fixture()
def lock(tmp_path: Path, host_bin: Path) -> Lock:
    return Lock(tmp_path, host_bin)


def body(group: str = "default") -> dict:
    return {"client_params": {"id": ID, "group": group}}


def test_without_a_server_both_verbs_do_nothing_and_succeed(lock: Lock, server: FleetLock) -> None:
    for verb in ("acquire", "release"):
        result = lock(verb)
        assert result.returncode == 0, result.output
        assert f"no FleetLock server configured ({lock.conf}, credential bluefin.reboot-lock.url); nothing to {verb}" in result.output
    assert server.requests == []


def test_a_config_file_with_only_comments_is_no_server(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"# URL=http://{server.base}\nGROUP=web\n")
    assert lock("acquire").returncode == 0
    assert server.requests == []


def test_acquire_posts_the_pre_reboot_request_and_holds_the_slot_on_200(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"URL=http://{server.base}/base/\n")
    result = lock("acquire")
    assert result.returncode == 0, result.output
    assert f"<6>holding a reboot slot on http://{server.base}/base (id {ID}, group default)\n" in result.stdout
    (request,) = server.requests
    assert request["path"] == "/base/v1/pre-reboot"
    assert request["headers"]["fleet-lock-protocol"] == "true"
    assert request["headers"]["Content-Type"] == "application/json"
    assert json.loads(request["body"]) == body()
    assert request["body"] == json.dumps(body(), separators=(",", ":"))


def test_redirects_are_not_followed(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"URL=http://{server.base}\n")
    server.code, server.headers = 302, {"Location": f"http://{server.base}/elsewhere"}
    result = lock("acquire")
    assert result.returncode == 1, result.output
    assert "HTTP 302" in result.output
    assert [r["path"] for r in server.requests] == ["/v1/pre-reboot"]


def test_release_posts_the_steady_state_request(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"URL=http://{server.base}\nGROUP=db-1\n")
    result = lock("release")
    assert result.returncode == 0, result.output
    assert "released the reboot slot" in result.output
    (request,) = server.requests
    assert request["path"] == "/v1/steady-state"
    assert json.loads(request["body"]) == body("db-1")


def test_a_full_semaphore_refuses_the_reboot_and_logs_the_servers_reason(lock: Lock, server: FleetLock) -> None:
    lock.configure(f'URL="http://{server.base}"\n')
    server.code = 409
    server.body = b'{"kind":"failed_lock_semaphore_full","value":"semaphore currently full"}\n'
    result = lock("acquire")
    assert result.returncode == 1, result.output
    assert result.stdout == (
        f"<4>no reboot slot on http://{server.base} (id {ID}, group default): HTTP 409 "
        '{"kind":"failed_lock_semaphore_full","value":"semaphore currently full"}; not rebooting\n'
    )


def test_any_answer_but_200_fails_a_release_so_the_unit_retries(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"URL=http://{server.base}\n")
    server.code = 500
    result = lock("release")
    assert result.returncode == 1, result.output
    assert f"<3>the reboot slot on http://{server.base} (id {ID}, group default) is not released: HTTP 500\n" in result.stdout
    # curl --retry 2: a 500 is transient, so three requests in all.
    assert len(server.requests) == 3


@pytest.mark.parametrize("code", [404, 503])
def test_a_server_that_answers_is_never_unreachable(lock: Lock, server: FleetLock, code: int) -> None:
    lock.configure(f"URL=http://{server.base}\n")
    server.code = code
    result = lock("acquire")
    assert result.returncode == 1, result.output
    assert f"HTTP {code}" in result.output and "not rebooting" in result.output
    assert "unreachable" not in result.output
    assert len(server.requests) == (3 if code == 503 else 1)


def test_an_unreachable_server_exits_3_not_1(lock: Lock, closed_port: int) -> None:
    # 1 would make bluefin-boot-deadline wait for the server; 3 lets it roll
    # back a boot whose update broke the network.
    lock.configure(f"URL=http://127.0.0.1:{closed_port}\n")
    result = lock("acquire")
    assert result.returncode == 3, result.output
    assert (
        f"<3>FleetLock server http://127.0.0.1:{closed_port}/v1/pre-reboot is unreachable "
        f"(id {ID}, group default): curl exit 7\n"
    ) in result.stdout
    assert "not rebooting" not in result.output
    result = lock("release")
    assert result.returncode == 3, result.output
    assert f"http://127.0.0.1:{closed_port}/v1/steady-state is unreachable" in result.output


def test_messages_show_the_url_without_its_credentials(lock: Lock, server: FleetLock, closed_port: int) -> None:
    lock.configure(f"URL=http://user:secret@{server.base}/base/\n")
    result = lock("acquire")
    assert result.returncode == 0, result.output
    assert f"holding a reboot slot on http://{server.base}/base (" in result.output
    assert "secret" not in result.output
    # The request still carries them, as HTTP basic authentication.
    auth = server.requests[-1]["headers"]["Authorization"]
    assert base64.b64decode(auth.removeprefix("Basic ")) == b"user:secret"

    server.code = 409
    result = lock("acquire")
    assert result.returncode == 1
    assert f"no reboot slot on http://{server.base}/base (" in result.output and "secret" not in result.output

    server.code = 404
    result = lock("release")
    assert result.returncode == 1
    assert f"the reboot slot on http://{server.base}/base (" in result.output and "secret" not in result.output

    lock.configure(f"URL=http://user:secret@127.0.0.1:{closed_port}/base\n")
    result = lock("acquire")
    assert result.returncode == 3
    assert f"FleetLock server http://127.0.0.1:{closed_port}/base/v1/pre-reboot is unreachable" in result.output
    assert "secret" not in result.output

    # An "@" in the password, against RFC 3986 but easy to write: curl splits
    # the user information off at the first "@" and refuses the rest as a
    # host name (exit 3); messages still hide everything before the last.
    server.code = 200
    requests = len(server.requests)
    lock.configure(f"URL=http://user:se@cret@{server.base}\n")
    result = lock("acquire")
    assert result.returncode == 3, result.output
    assert f"FleetLock server http://{server.base}/v1/pre-reboot is unreachable (id {ID}, group default): curl exit 3\n" in result.stdout
    assert "cret" not in result.output
    assert len(server.requests) == requests

    # Percent-encoded, it is sent.
    lock.configure(f"URL=http://user:se%40cret@{server.base}\n")
    result = lock("acquire")
    assert result.returncode == 0, result.output
    assert f"holding a reboot slot on http://{server.base} (" in result.output
    auth = server.requests[-1]["headers"]["Authorization"]
    assert base64.b64decode(auth.removeprefix("Basic ")) == b"user:se@cret"

    # Refused before any request, still without them.
    for bad in ("ftp://user:secret@fleetlock.example", "user:secret@fleetlock.example"):
        lock.configure(f"URL={bad}\n")
        result = lock("acquire")
        assert result.returncode == 1
        assert "fleetlock.example is not an http(s) URL" in result.output
        assert "secret" not in result.output


def test_credentials_on_a_plain_http_url_are_sent_with_a_warning(lock: Lock, server: FleetLock, closed_port: int) -> None:
    lock.configure(f"URL=http://user:secret@{server.base}/\n")
    result = lock("acquire")
    assert result.returncode == 0, result.output
    assert f"<4>FleetLock URL http://{server.base} carries credentials over plain http; they are sent in clear\n" in result.stdout
    assert "secret" not in result.output

    lock.configure(f"URL=https://user:secret@127.0.0.1:{closed_port}/\n")
    assert "plain http" not in lock("acquire").output

    lock.configure(f"URL=http://{server.base}/\n")
    assert "plain http" not in lock("acquire").output


def test_quotes_and_backslashes_in_a_password_reach_the_server(lock: Lock, server: FleetLock) -> None:
    # curl's config quoting carried these; net/url refuses them in a URL.
    lock.configure(f'URL=http://user:p"a\\ss@{server.base}\n')
    result = lock("acquire")
    assert result.returncode == 0, result.output
    auth = server.requests[-1]["headers"]["Authorization"]
    assert base64.b64decode(auth.removeprefix("Basic ")) == b'user:p"a\\ss'


def test_credentials_override_the_config_file(lock: Lock, server: FleetLock, closed_port: int) -> None:
    lock.configure(f"URL=http://127.0.0.1:{closed_port}\nGROUP=file\n")
    (lock.creds / "bluefin.reboot-lock.url").write_text(f"http://{server.base}\n", encoding="utf-8")
    (lock.creds / "bluefin.reboot-lock.group").write_text("workers\n", encoding="utf-8")
    result = lock("acquire")
    assert result.returncode == 0, result.output
    assert json.loads(server.requests[-1]["body"]) == body("workers")


def test_a_url_credential_alone_configures_the_lock(lock: Lock, server: FleetLock) -> None:
    (lock.creds / "bluefin.reboot-lock.url").write_text(f"http://{server.base}", encoding="utf-8")
    result = lock("acquire")
    assert result.returncode == 0, result.output
    assert json.loads(server.requests[-1]["body"]) == body()


def test_a_group_outside_the_protocols_alphabet_is_refused_without_a_request(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"URL=http://{server.base}\nGROUP=web servers\n")
    result = lock("acquire")
    assert result.returncode == 1
    assert "<3>FleetLock group web servers must match [a-zA-Z0-9.-]+; not rebooting\n" in result.stdout
    assert server.requests == []


def test_a_url_that_is_not_http_is_refused_without_a_request(lock: Lock, server: FleetLock) -> None:
    lock.configure("URL=file:///etc/passwd\n")
    result = lock("acquire")
    assert result.returncode == 1
    assert server.requests == []


def test_no_client_id_means_no_reboot(lock: Lock, server: FleetLock) -> None:
    lock.configure(f"URL=http://{server.base}\n")
    lock.id128("exit 1\n")
    result = lock("acquire")
    assert result.returncode == 1
    assert "cannot derive the FleetLock client id" in result.output
    assert server.requests == []


def test_an_unknown_verb_is_a_usage_error(lock: Lock) -> None:
    result = lock("reboot")
    assert result.returncode == 2
    assert result.stderr == "usage: bluefin-reboot-lock acquire|release\n"
