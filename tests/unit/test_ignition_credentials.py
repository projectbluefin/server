"""Executed coverage for bluefin-ignition-credentials.

bluefin-ignition-credentials stages an Ignition config from a system credential
or, for a network-booted node, from bluefin-node.ign next to the UKI. The
node config used to be applied with no signature: an on-path attacker on the
(often plain-HTTP) provisioning network got root despite the signed boot
chain. The signature is now the gate, whatever the transport: a config next to
the UKI is applied only if bluefin-node.ign.gpg verifies against the Ignition
config keyring in the initrd (never the release keyring that authenticates
SHA256SUMS), or, unsigned (the .gpg is a 404, nothing else), with the
bluefin.ignition.allow-unsigned credential, which the netboot UKI sets while
the ignition_allow_unsigned build option is on (projectbluefin/server#327).
Runs against local HTTP and HTTPS servers and throwaway GnuPG keys; no
files/boot-keys are needed.
"""

from __future__ import annotations

import functools
import os
import shutil
import stat
import subprocess
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "files" / "initrd-ignition" / "usr" / "libexec" / "bluefin-ignition-credentials"
UNIT = ROOT / "files" / "initrd-ignition" / "usr" / "lib" / "systemd" / "system" / "bluefin-ignition-credentials.service"
ELEMENTS = ROOT / "elements" / "bluefin-server" / "initrd"
BOOT = ROOT / "elements" / "oci" / "bluefin-server-boot.bst"
PROJECT = ROOT / "project.conf"
DEFAULT_KEYRING = "/usr/lib/bluefin/ignition-pubring.pgp"
needs_tools = pytest.mark.skipif(
    not all(shutil.which(t) for t in ("curl", "gpg", "gpgv", "openssl")),
    reason="needs curl, gpg, gpgv and openssl",
)

# The release keyring's paths; a private user and mount namespace lets a test
# put a keyring there that the script must never use.
KEYRING_DIRS = ("/etc/systemd", "/usr/lib/systemd")


def _can_bind_keyring_dirs() -> bool:
    if not shutil.which("unshare") or not all(os.path.isdir(d) for d in KEYRING_DIRS):
        return False
    mounts = " && ".join(f"mount -t tmpfs none {d}" for d in KEYRING_DIRS)
    probe = subprocess.run(
        ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", mounts], capture_output=True
    )
    return probe.returncode == 0


needs_mount_ns = pytest.mark.skipif(not _can_bind_keyring_dirs(), reason="needs unprivileged user and mount namespaces")

CONFIG = """\
{"ignition":{"version":"3.6.0"},"systemd":{"units":[{"name":"x.service","enabled":true,"contents":"[Unit]\\n[Service]\\nExecStart=/bin/true\\n[Install]\\nWantedBy=multi-user.target\\n"}]}}
"""


def test_ships_in_the_initrd_stack_and_is_executable_bash() -> None:
    import yaml

    stack = yaml.safe_load((ELEMENTS / "initrd-stack.bst").read_text(encoding="utf-8"))["depends"]
    assert "bluefin-server/initrd/initrd-ignition-stack.bst" in stack
    doc = yaml.safe_load((ELEMENTS / "initrd-ignition-stack.bst").read_text(encoding="utf-8"))
    assert doc["kind"] == "stack"
    assert "bluefin-server/initrd/initrd-ignition.bst" in doc["depends"]
    assert "bluefin-server/initrd/initrd-ignition-keys.bst" in doc["depends"]
    assert SCRIPT.read_text(encoding="utf-8").startswith("#!/usr/bin/bash\n")
    assert SCRIPT.stat().st_mode & stat.S_IXUSR
    subprocess.run(["bash", "-n", str(SCRIPT)], check=True)


def test_the_script_is_shellcheck_clean(shellcheck: str) -> None:
    subprocess.run([shellcheck, "-S", "style", str(SCRIPT)], check=True)


@pytest.fixture(scope="module")
def keys(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    base = tmp_path_factory.mktemp("gpg")
    out = {}
    for name in ("config", "release", "stranger"):
        home = base / name
        home.mkdir(mode=0o700)
        env = dict(os.environ, GNUPGHOME=str(home))
        subprocess.run(
            ["gpg", "--batch", "--quiet", "--passphrase", "", "--quick-gen-key",
             f"{name} <{name}@example.invalid>", "ed25519", "sign", "never"],
            check=True, env=env, capture_output=True,
        )
        ring = base / f"{name}.pgp"
        subprocess.run(["gpg", "--batch", "--export", "--output", str(ring)], check=True, env=env, capture_output=True)
        out[name] = home
        out[f"{name}-ring"] = ring
    return out


class Handler(SimpleHTTPRequestHandler):
    """Serves a directory; FAIL maps a request path to an HTTP status, or to
    "drop" to close the connection without a response."""

    FAIL: dict[str, int | str] = {}

    def log_message(self, *args) -> None:
        pass

    def _override(self) -> bool:
        action = self.FAIL.get(self.path)
        if action is None:
            return False
        if action == "drop":
            self.close_connection = True
            self.connection.shutdown(2)
        else:
            self.send_error(int(action))
        return True

    def do_GET(self) -> None:
        if not self._override():
            super().do_GET()

    def do_HEAD(self) -> None:
        if not self._override():
            super().do_HEAD()


def _serve(root: Path, fail: dict[str, int | str], cert_dir: Path | None) -> tuple[ThreadingHTTPServer, str]:
    import ssl

    handler = type("H", (Handler,), {"FAIL": fail})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(handler, directory=str(root)))
    scheme = "http"
    if cert_dir is not None:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_dir / "cert.pem"), keyfile=str(cert_dir / "key.pem"))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"{scheme}://127.0.0.1:{httpd.server_address[1]}"


@pytest.fixture()
def origin(tmp_path: Path):
    """A plain-HTTP boot server: (url, served directory, FAIL overrides)."""
    srv = tmp_path / "srv"
    srv.mkdir()
    fail: dict[str, int | str] = {}
    httpd, url = _serve(srv, fail, None)
    yield url, srv, fail
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture()
def tls_origin(tmp_path: Path):
    """The same over HTTPS; curl trusts its self-signed cert via CURL_CA_BUNDLE."""
    srv = tmp_path / "tls-srv"
    srv.mkdir()
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", "key.pem", "-out", "cert.pem",
         "-days", "1", "-nodes", "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1"],
        check=True, cwd=tmp_path, capture_output=True,
    )
    httpd, url = _serve(srv, {}, tmp_path)
    yield url, srv
    httpd.shutdown()
    httpd.server_close()


def _publish(directory: Path, *, config: str = CONFIG, sign_key: Path | None = None) -> None:
    (directory / "bluefin-server-netboot.efi").write_text("uki", encoding="utf-8")
    (directory / "bluefin-node.ign").write_text(config, encoding="utf-8")
    if sign_key is not None:
        subprocess.run(
            ["gpg", "--batch", "--yes", "--detach-sign", "--output",
             str(directory / "bluefin-node.ign.gpg"), str(directory / "bluefin-node.ign")],
            check=True, env=dict(os.environ, GNUPGHOME=str(sign_key)), capture_output=True,
        )


def run(
    tmp_path: Path,
    *,
    origin_url: str | None = None,
    creds: dict[str, str] | None = None,
    keyring: Path | None = None,
    keyring_dirs: tuple[Path, Path] | None = None,
) -> tuple[int, str, str | None]:
    """Run bluefin-ignition-credentials. Returns (returncode, combined output,
    the staged user.ign contents or None if nothing was staged). keyring_dirs
    are bound over KEYRING_DIRS in a private mount namespace."""
    out = tmp_path / "run" / "ignition"
    out.mkdir(parents=True)
    env = dict(os.environ, BLUEFIN_IGNITION_OUT=str(out / "user.ign"), CURL_CA_BUNDLE=str(tmp_path / "cert.pem"))
    env.pop("CREDENTIALS_DIRECTORY", None)
    env.pop("BLUEFIN_IGNITION_KEYRING", None)
    if keyring is not None:
        env["BLUEFIN_IGNITION_KEYRING"] = str(keyring)
    if creds:
        cred_dir = tmp_path / "creds"
        cred_dir.mkdir(exist_ok=True)
        for name, value in creds.items():
            (cred_dir / name).write_text(value, encoding="utf-8")
        env["CREDENTIALS_DIRECTORY"] = str(cred_dir)
    if origin_url is not None:
        # A stand-in for /usr/libexec/bluefin-boot-origin: it reports the URL the
        # node booted from (the UKI URL; the config lives next to it).
        bo = tmp_path / "boot-origin"
        bo.write_text(f'#!/usr/bin/bash\nprintf "%s\\n" "{origin_url}"\n', encoding="utf-8")
        bo.chmod(0o755)
        env["BLUEFIN_BOOT_ORIGIN"] = str(bo)
    cmd = [str(SCRIPT)]
    if keyring_dirs is not None:
        binds = " && ".join(f'mount --bind "${i + 1}" {d}' for i, d in enumerate(KEYRING_DIRS))
        cmd = ["unshare", "--user", "--map-root-user", "--mount", "sh", "-c", f'{binds} && exec "$3"',
               "sh", *map(str, keyring_dirs), str(SCRIPT)]
    result = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=120)
    user_ign = out / "user.ign"
    contents = user_ign.read_text(encoding="utf-8") if user_ign.exists() else None
    return result.returncode, result.stdout + result.stderr, contents


UKI = "/bluefin-server-netboot.efi"
ALLOW = {"bluefin.ignition.allow-unsigned": "1"}


@needs_tools
def test_signed_config_over_plain_http_is_staged_verbatim(tmp_path: Path, origin, keys) -> None:
    url, srv, _ = origin
    _publish(srv, sign_key=keys["config"])
    rc, log, contents = run(tmp_path, origin_url=url + UKI, keyring=keys["config-ring"])
    assert rc == 0, log
    assert contents == CONFIG, "the verified bytes are staged, not re-fetched"
    assert f"gpgv-verified against {keys['config-ring']}" in log
    assert 'gpgv: Good signature from "config' in log, "gpgv's report reaches the journal"


@needs_tools
def test_signed_config_over_https_is_staged_verbatim(tmp_path: Path, tls_origin, keys) -> None:
    url, srv = tls_origin
    _publish(srv, sign_key=keys["config"])
    rc, log, contents = run(tmp_path, origin_url=url + UKI, keyring=keys["config-ring"])
    assert rc == 0, log
    assert contents == CONFIG


@needs_tools
def test_the_signing_helper_signs_what_a_node_accepts(tmp_path: Path, origin, keys) -> None:
    # scripts/sign-node-config.sh is the documented operator procedure.
    url, srv, _ = origin
    _publish(srv)
    secret = tmp_path / "ignition-signing.asc"
    secret.write_bytes(subprocess.run(
        ["gpg", "--batch", "--armor", "--export-secret-keys"],
        check=True, capture_output=True, env=dict(os.environ, GNUPGHOME=str(keys["config"])),
    ).stdout)
    subprocess.run(["bash", str(ROOT / "scripts" / "sign-node-config.sh"), str(secret), str(srv / "bluefin-node.ign")],
                   check=True, capture_output=True)
    rc, log, contents = run(tmp_path, origin_url=url + UKI, keyring=keys["config-ring"])
    assert rc == 0, log
    assert contents == CONFIG


@needs_tools
def test_http_origin_without_a_config_boots_with_nothing_to_apply(tmp_path: Path, origin, keys) -> None:
    url, _, _ = origin
    rc, log, contents = run(tmp_path, origin_url=url + UKI, keyring=keys["config-ring"])
    assert rc == 0, log
    assert contents is None
    assert "nothing to apply" in log


@needs_tools
@pytest.mark.parametrize(
    "damage,reason",
    [
        ("release-key", "No public key"),
        ("other-key", "No public key"),
        ("config-changed", "BAD signature"),
        ("signature-truncated", "gpgv: "),
    ],
)
def test_a_signature_that_does_not_verify_is_refused(tmp_path: Path, origin, keys, damage: str, reason: str) -> None:
    # release-key: a config signed with the key that signs SHA256SUMS is not a
    # config the Ignition config keyring vouches for.
    url, srv, _ = origin
    signer = {"release-key": "release", "other-key": "stranger"}.get(damage, "config")
    _publish(srv, sign_key=keys[signer])
    if damage == "config-changed":
        (srv / "bluefin-node.ign").write_text(CONFIG.replace("/bin/true", "/bin/sh"), encoding="utf-8")
    if damage == "signature-truncated":
        sig = srv / "bluefin-node.ign.gpg"
        sig.write_bytes(sig.read_bytes()[:-8])
    rc, log, contents = run(tmp_path, origin_url=url + UKI, creds=ALLOW, keyring=keys["config-ring"])
    assert rc == 1, log
    assert contents is None
    assert "does not verify" in log
    assert reason in log, "the journal says why gpgv refused"


@needs_tools
@pytest.mark.parametrize("scheme", ["http", "HTTP"])
def test_an_unsigned_config_is_refused_without_the_opt_out(tmp_path: Path, origin, keys, scheme: str) -> None:
    url, srv, _ = origin
    _publish(srv)
    rc, log, contents = run(tmp_path, origin_url=url.replace("http", scheme, 1) + UKI, keyring=keys["config-ring"])
    assert rc == 1, log
    assert contents is None
    assert "bluefin.ignition.allow-unsigned is not set" in log


@needs_tools
def test_an_unsigned_config_is_staged_verbatim_with_the_opt_out(tmp_path: Path, origin, keys) -> None:
    url, srv, _ = origin
    _publish(srv)
    rc, log, contents = run(tmp_path, origin_url=url + UKI, creds=ALLOW, keyring=keys["config-ring"])
    assert rc == 0, log
    assert contents == CONFIG
    assert "UNAUTHENTICATED" in log


@needs_tools
@pytest.mark.parametrize("failure", [500, "drop"])
def test_a_signature_that_cannot_be_fetched_is_not_a_missing_one(tmp_path: Path, origin, keys, failure) -> None:
    url, srv, fail = origin
    _publish(srv, sign_key=keys["config"])
    fail["/bluefin-node.ign.gpg"] = failure
    rc, log, contents = run(tmp_path, origin_url=url + UKI, creds=ALLOW, keyring=keys["config-ring"])
    assert rc == 1, log
    assert contents is None


@needs_tools
@pytest.mark.parametrize("kind", ["missing", "dangling-symlink", "directory"])
def test_an_unreadable_keyring_refuses_a_signed_config(tmp_path: Path, origin, keys, kind: str) -> None:
    url, srv, _ = origin
    _publish(srv, sign_key=keys["config"])
    ring = tmp_path / "ignition-pubring.pgp"
    if kind == "dangling-symlink":
        ring.symlink_to(tmp_path / "gone.pgp")
    if kind == "directory":
        ring.mkdir()
    rc, log, contents = run(tmp_path, origin_url=url + UKI, keyring=ring)
    assert rc == 1, log
    assert contents is None
    assert f"Ignition config keyring {ring} is missing or unreadable" in log
    assert "gpgv:" not in log, "no other keyring is tried"


@needs_tools
@needs_mount_ns
@pytest.mark.skipif(os.path.exists(DEFAULT_KEYRING), reason=f"{DEFAULT_KEYRING} exists on this host")
def test_the_release_keyring_never_verifies_a_node_config(tmp_path: Path, origin, keys) -> None:
    # Domain separation: with the release keyring in both places
    # systemd-importd reads it from, a config signed with the release key is
    # still refused. The script reads only its own keyring, absent here.
    url, srv, _ = origin
    _publish(srv, sign_key=keys["release"])
    etc, usr = tmp_path / "etc-systemd", tmp_path / "usr-lib-systemd"
    etc.mkdir()
    usr.mkdir()
    for d in (etc, usr):
        shutil.copy(keys["release-ring"], d / "import-pubring.pgp")
    rc, log, contents = run(tmp_path, origin_url=url + UKI, creds=ALLOW, keyring_dirs=(etc, usr))
    assert rc == 1, log
    assert contents is None
    assert f"Ignition config keyring {DEFAULT_KEYRING} is missing or unreadable" in log
    assert "gpgv:" not in log


def test_the_initrd_ships_the_ignition_config_keyring_from_the_key_set() -> None:
    import yaml

    doc = yaml.safe_load((ELEMENTS / "initrd-ignition-keys.bst").read_text(encoding="utf-8"))
    assert doc["kind"] == "import"
    assert doc["sources"] == [{"kind": "local", "path": "files/boot-keys/ignition-pubring.pgp"}]
    assert doc["config"]["target"] + "/ignition-pubring.pgp" == DEFAULT_KEYRING
    assert f'"${{BLUEFIN_IGNITION_KEYRING:-{DEFAULT_KEYRING}}}"' in SCRIPT.read_text(encoding="utf-8")


def test_only_the_netboot_uki_accepts_an_unsigned_node_config_by_default() -> None:
    # Transitional until Booty signs per-node configs (#327): UEFI HTTP Boot
    # with Secure Boot cannot pass the opt-out except on the UKI's own
    # command line. One build option, on by default, puts it there; installed
    # and installer boots never get it.
    import yaml

    option = yaml.safe_load(PROJECT.read_text(encoding="utf-8"))["options"]["ignition_allow_unsigned"]
    assert option["type"] == "bool"
    assert option["default"] is True, "flip to False once Booty signs node configs (booty-integration.md)"

    text = BOOT.read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    variables = doc["variables"]
    assert variables["netboot-ignition-cmdline"] == ""
    assert "%{netboot-ignition-cmdline}" in variables["netboot-cmdline"].split()
    assert doc["(?)"] == [
        {"ignition_allow_unsigned": {"variables": {
            "netboot-ignition-cmdline": "systemd.set_credential=bluefin.ignition.allow-unsigned:1"}}}
    ]
    assert text.count("bluefin.ignition.allow-unsigned:1") == 1
    for name in ("common-cmdline", "disk-cmdline", "installer-cmdline"):
        assert "ignition" not in variables[name], name
    assert text.count("%{netboot-cmdline}") == 1
    assert 'uki bluefin-server-netboot_%{image-version} "%{netboot-cmdline}"' in text
    assert "ImportCredential=bluefin.ignition.allow-unsigned" in UNIT.read_text(encoding="utf-8").splitlines()


@needs_tools
def test_ignition_config_credential_is_staged_inline(tmp_path: Path) -> None:
    rc, log, contents = run(tmp_path, creds={"ignition.config": CONFIG})
    assert rc == 0, log
    assert contents == CONFIG


@needs_tools
@pytest.mark.parametrize("url", ["http://10.0.2.2:8765/bluefin-node.ign", "https://10.0.2.2/bluefin-node.ign"])
def test_config_url_credential_is_staged_as_replace(tmp_path: Path, url: str) -> None:
    rc, log, contents = run(tmp_path, creds={"ignition.config.url": url})
    assert rc == 0, log
    assert contents is not None
    assert '"replace":{"source":"' + url + '"}' in contents


@needs_tools
def test_no_credential_and_no_boot_origin_is_a_no_op(tmp_path: Path) -> None:
    rc, log, contents = run(tmp_path)
    assert rc == 0, log
    assert contents is None
    assert "nothing to apply" in log
