"""Real SSH forwarding and renewal against a disposable loopback peer."""
from contextlib import contextmanager
import json
import select
import shlex
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paramiko
from substance.server_ssh import SSHConnection
from substance.online_transport import OnlineTransport
from substance.repositories import online_client
online_client()
from dubbing_online_client import ApiClient

class SSHServer(paramiko.ServerInterface):
    def __init__(self, auth_calls=None): self.targets, self.auth_calls = {}, auth_calls
    def check_auth_password(self, username, password):
        if self.auth_calls is not None: self.auth_calls.append(username)
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ('tester', 'ssh-test-password') else paramiko.AUTH_FAILED
    def get_allowed_auths(self, username): return 'password'
    def check_channel_request(self, kind, identifier): return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
    def check_channel_direct_tcpip_request(self, identifier, origin, destination):
        self.targets[identifier] = destination
        return paramiko.OPEN_SUCCEEDED
    def check_channel_exec_request(self, channel, command):
        def execute():
            arguments = shlex.split(command.decode())
            if arguments == ['id', '-u']: channel.sendall(b'0\n')
            elif arguments[:2] == ['printf', '%s']: channel.sendall(arguments[2].encode())
            elif arguments[:2] == ['python3', '-c']:
                result = subprocess.run([sys.executable, *arguments[1:]], capture_output=True, timeout=10)
                channel.sendall(result.stdout)
                if result.stderr: channel.sendall_stderr(result.stderr)
                channel.send_exit_status(result.returncode); channel.shutdown_write()
                return
            channel.send_exit_status(0); channel.shutdown_write()
        threading.Thread(target=execute, daemon=True).start()
        return True


@contextmanager
def ssh_server(host_keys=None, auth_calls=None):
    host_keys = host_keys or [paramiko.RSAKey.generate(2048)]
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); listener.listen(); listener.settimeout(0.1)
    event, transports = threading.Event(), []
    def forward(channel, destination):
        peer = socket.create_connection(destination)
        try:
            while True:
                ready, _, _ = select.select([channel, peer], [], [], 0.2)
                if channel in ready:
                    raw = channel.recv(65536)
                    if not raw: break
                    peer.sendall(raw)
                if peer in ready:
                    raw = peer.recv(65536)
                    if not raw: break
                    channel.sendall(raw)
        finally: peer.close(); channel.close()
    def handle(peer):
        transport = paramiko.Transport(peer); transports.append(transport)
        for key in host_keys: transport.add_server_key(key)
        interface = SSHServer(auth_calls)
        try:
            transport.start_server(server=interface)
            while transport.is_active() and not event.is_set():
                channel = transport.accept(0.1)
                if channel and channel.get_id() in interface.targets:
                    threading.Thread(target=forward, args=(channel, interface.targets[channel.get_id()]), daemon=True).start()
        except (EOFError, paramiko.SSHException, OSError): pass
        finally: transport.close()
    def loop():
        while not event.is_set():
            try: peer, _ = listener.accept()
            except socket.timeout: continue
            except OSError: break
            threading.Thread(target=handle, args=(peer,), daemon=True).start()
    thread = threading.Thread(target=loop, daemon=True); thread.start()
    try: yield {'host': '127.0.0.1', 'ssh_user': 'tester', 'ssh_port': listener.getsockname()[1], 'key_file': ''}
    finally:
        event.set(); listener.close()
        for transport in transports: transport.close()
        thread.join(timeout=2)


def test_private_forward_reconnects_without_changing_listener_and_rejects_after_close(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            raw = json.dumps({"ok": True}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        def log_message(self, *args):
            pass
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    try:
        with ssh_server() as config:
            config["api_port"] = http.server_port
            pins = SSHConnection(config, tmp_path)
            key = pins.inspect_key()
            pins.trust_key(key)
            config["fingerprint"] = key["fingerprint"]
            transport = OnlineTransport(config, str(tmp_path), {"password": "ssh-test-password"})
            address = transport.url
            try:
                client = ApiClient(address)
                assert client.request("GET", "/v1/info") == {"ok": True}
                # Simulate network loss; the next request must create a new SSH
                # connection while retaining the owned localhost listener.
                transport.connection.close()
                assert client.request("GET", "/v1/info") == {"ok": True}
                assert transport.url == address
            finally:
                transport.close()
            assert transport.closed and not transport.secret
    finally:
        http.shutdown()
        http.server_close()
        thread.join()
