"""A renewable SSH listener owned by this editor, independent of DubbingManager."""

import select
import socketserver
import threading

from .server_ssh import SSHConnection, ssh_parameters


class _Forward(socketserver.BaseRequestHandler):
    def handle(self):
        channel = None
        try:
            transport = self.server.owner.transport()
            channel = transport.open_channel("direct-tcpip", ("127.0.0.1", self.server.owner.port),
                                             self.request.getpeername(), timeout=15)
            if channel is None:
                return
            while not self.server.owner.closed:
                ready, _, _ = select.select([self.request, channel], [], [], 1)
                if self.request in ready:
                    data = self.request.recv(65536)
                    if not data:
                        break
                    channel.sendall(data)
                if channel in ready:
                    data = channel.recv(65536)
                    if not data:
                        break
                    self.request.sendall(data)
        except Exception:
            # The HTTP client reports the closed stream as a transport error.
            pass
        finally:
            if channel:
                channel.close()


class _Server(socketserver.ThreadingTCPServer):
    daemon_threads = True


class OnlineTransport:
    def __init__(self, config, directory, secret):
        self.config = ssh_parameters(config)
        self.port = config.get("api_port", 8000)
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("Проверьте порт API SSH-сервера")
        self.directory, self.secret = directory, dict(secret)
        self.lock = threading.Lock()
        self.closed, self.connection, self.server = False, None, None
        try:
            self.transport()
            self.server = _Server(("127.0.0.1", 0), _Forward)
            self.server.owner = self
            self.url = "http://127.0.0.1:" + str(self.server.server_address[1])
            self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name="substance-ssh")
            self.thread.start()
        except BaseException:
            self.close()
            raise

    def transport(self):
        with self.lock:
            if self.closed:
                raise ValueError("SSH-подключение закрыто")
            current = self.connection.client.get_transport() if self.connection and self.connection.client else None
            if current and current.is_active():
                return current
            if self.connection:
                self.connection.close()
            self.connection = SSHConnection(self.config, self.directory, **self.secret).connect()
            return self.connection.client.get_transport()

    def close(self):
        with self.lock:
            if self.closed:
                return
            self.closed = True
            if self.connection:
                self.connection.close()
            self.secret.clear()
        if self.server:
            self.server.shutdown()
            self.server.server_close()
