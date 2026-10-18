"""Real loopback SSH handshake/auth/channel tests; no production host involved."""
from contextlib import suppress
import socket
import shlex
import subprocess
import sys
import threading

import paramiko
import pytest

from substance.server_ssh import SSHConnection, SSHHostKeyChanged, fingerprint


@pytest.fixture
def peer(tmp_path):
    hostkey, clientkey = paramiko.RSAKey.generate(2048), paramiko.RSAKey.generate(2048)
    keyfile = tmp_path / 'client-key'
    clientkey.write_private_key_file(str(keyfile))
    keyfile.chmod(0o600)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen()
    listener.settimeout(0.2)
    stopped, auth = threading.Event(), []
    transports, handlers = [], []
    class Server(paramiko.ServerInterface):
        def get_allowed_auths(self, username):
            return 'publickey'
        def check_auth_publickey(self, username, key):
            auth.append(username)
            return paramiko.AUTH_SUCCESSFUL if username == 'tester' and key == clientkey else paramiko.AUTH_FAILED
        def check_channel_request(self, kind, chanid):
            return paramiko.OPEN_SUCCEEDED if kind == 'session' else paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED
        def check_channel_exec_request(self, channel, command):
            def execute():
                data = bytearray()
                while chunk := channel.recv(65536):
                    data.extend(chunk)
                if command == b'id -u':
                    out, errors, status = b'1000\n', b'', 0
                else:
                    result = subprocess.run(shlex.split(command.decode()), input=bytes(data), capture_output=True, timeout=5)
                    out, errors, status = result.stdout, result.stderr, result.returncode
                with suppress(OSError, EOFError):
                    channel.sendall(out)
                    channel.sendall_stderr(errors)
                    channel.send_exit_status(status)
                    channel.close()
            thread = threading.Thread(target=execute, daemon=True)
            handlers.append(thread)
            thread.start()
            return True
    def serve():
        while not stopped.is_set():
            try:
                conn, _ = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            transport = paramiko.Transport(conn)
            transports.append(transport)
            transport.add_server_key(hostkey)
            with suppress(EOFError, OSError, paramiko.SSHException):
                transport.start_server(server=Server())
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    config = {'host': '127.0.0.1', 'ssh_user': 'tester', 'ssh_port': listener.getsockname()[1], 'key_file': str(keyfile)}
    try:
        yield config, tmp_path / 'pins', hostkey, auth
    finally:
        stopped.set()
        listener.close()
        for transport in transports:
            transport.close()
        thread.join(2)
        for handler in handlers:
            handler.join(2)


def test_verified_real_ssh_auth_and_private_stdin_channel(peer):
    config, pins, hostkey, auth = peer
    connection = SSHConnection(config, pins)
    key = connection.inspect_key()
    assert not key['known'] and key['fingerprint'] == fingerprint(hostkey) and not auth
    with pytest.raises(ValueError):
        connection.connect()  # RejectPolicy blocks authentication before trust
    assert not auth
    connection.trust_key(key)
    connection.config['fingerprint'] = key['fingerprint']
    try:
        connection.connect()
        assert auth and not connection.root_user
        result = connection.command([sys.executable, '-c', 'import sys;print(sys.stdin.read())'], input=b'private stdin payload')
        assert result.strip() == 'private stdin payload'
        assert connection.inspect_key()['known']
    finally:
        connection.close()
    assert connection.client is None


def test_real_ssh_key_mismatch_rejected_before_auth(peer):
    config, pins, hostkey, auth = peer
    connection = SSHConnection({**config, 'fingerprint': 'SHA256:wrong'}, pins)
    with pytest.raises(SSHHostKeyChanged):
        connection.inspect_key()
    assert not auth
