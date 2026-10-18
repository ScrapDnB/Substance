"""SSH transport for the LibreTranslate wizard. Host keys are explicitly pinned."""
import base64
import hashlib
import json
from pathlib import Path
import shlex
import socket
import time
from uuid import uuid4


def fingerprint(key):
    return 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')


class SSHHostKeyChanged(ValueError):
    def __init__(self, key):
        super().__init__('SSH-ключ отличается от закреплённого или сохранённого. Сверьте новый отпечаток у провайдера; смена пароля не устранит это сообщение.')
        self.host_key = key


def sudo_command(arguments):
    # Consume the password ourselves first. sudo may be configured NOPASSWD and
    # otherwise leave that line in the JSON input of the actual root command.
    script = 'IFS= read -r substance_sudo_secret; printf "%s\\n" "$substance_sudo_secret" | sudo -S -p "" -v && unset substance_sudo_secret && exec sudo -n -- "$@"'
    return shlex.join(['sh', '-c', script, 'substance', *map(str, arguments)])


def ssh_parameters(value):
    import re
    result = dict(value)
    host = str(value.get('host', '')).strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.:-]{0,252}', host):
        raise ValueError('Укажите IP или имя сервера без http:// и пробелов.')
    user = str(value.get('ssh_user', 'root')).strip()
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}', user):
        raise ValueError('Проверьте имя пользователя SSH.')
    port = value.get('ssh_port', 22)
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError('Порт SSH должен быть от 1 до 65535.')
    result.update(host=host, ssh_user=user, ssh_port=port)
    return result


class SSHConnection:
    def __init__(self, config, directory, *, password='', sudo_password='', key_passphrase='', cancel=None):
        self.config = ssh_parameters(config)
        self.password, self.sudo_password, self.key_passphrase = password, sudo_password, key_passphrase
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cancel, self.client, self.root_user = cancel, None, False

    @property
    def host_id(self):
        return self.config['host'] if self.config['ssh_port'] == 22 else f"[{self.config['host']}]:{self.config['ssh_port']}"

    def _known_keys(self):
        import paramiko
        keys = {}
        # An explicitly trusted application key overrides the user's SSH file
        # for this application only. Never rewrite ~/.ssh/known_hosts.
        for path in (Path.home() / '.ssh/known_hosts', self.directory / 'known_hosts'):
            if path.exists():
                keys.update(paramiko.HostKeys(str(path)).lookup(self.host_id) or {})
        return keys

    def inspect_key(self):
        import paramiko
        keys = self._known_keys()
        pinned = self.config.get('fingerprint')
        transport = paramiko.Transport(socket.create_connection((self.config['host'], self.config['ssh_port']), timeout=15))
        try:
            # Match SSHClient's preference for a known host-key algorithm.
            # A server can legitimately offer RSA, ECDSA and Ed25519 keys.
            preferred = {kind for kind, key in keys.items() if not pinned or fingerprint(key) == pinned}
            if 'ssh-rsa' in preferred:
                preferred.update(('rsa-sha2-512', 'rsa-sha2-256'))
            options = transport.get_security_options()
            options.key_types = tuple(kind for kind in options.key_types if kind in preferred) + tuple(kind for kind in options.key_types if kind not in preferred)
            transport.start_client(timeout=15)
            key = transport.get_remote_server_key()
            value = {'fingerprint': fingerprint(key), 'key_type': key.get_name(), 'key': key.get_base64(),
                     'known': keys.get(key.get_name()) == key}
            if (pinned and value['fingerprint'] != pinned) or (keys and not value['known']):
                previous = [pinned] if pinned else [fingerprint(old) for old in keys.values()]
                value.update(changed=True, known=False, previous_fingerprints=list(dict.fromkeys(previous)))
                raise SSHHostKeyChanged(value)
            return value
        finally:
            transport.close()

    def trust_key(self, key):
        import paramiko
        path = self.directory / 'known_hosts'
        keys = paramiko.HostKeys(str(path)) if path.exists() else paramiko.HostKeys()
        parsed = paramiko.PKey.from_type_string(key['key_type'], base64.b64decode(key['key']))
        if fingerprint(parsed) != key['fingerprint']:
            raise ValueError('SSH-ключ не совпал с показанным отпечатком.')
        keys.add(self.host_id, key['key_type'], parsed)
        temporary = path.with_name('.known-hosts-' + uuid4().hex)
        keys.save(str(temporary))
        temporary.chmod(0o600)
        temporary.replace(path)

    def connect(self):
        import paramiko
        client = paramiko.SSHClient()
        keys = self._known_keys()
        pinned = self.config.get('fingerprint')
        for kind, key in keys.items():
            if not pinned or fingerprint(key) == pinned:
                client.get_host_keys().add(self.host_id, kind, key)
        if pinned and not client.get_host_keys().lookup(self.host_id):
            raise ValueError('Сначала проверьте и подтвердите SSH-ключ сервера в мастере подключения.')
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(self.config['host'], port=self.config['ssh_port'], username=self.config['ssh_user'],
                           password=self.password or None, key_filename=self.config.get('key_file') or None,
                           passphrase=self.key_passphrase or None, look_for_keys=not bool(self.password), allow_agent=not bool(self.password),
                           timeout=15, auth_timeout=20, banner_timeout=20)
            key = client.get_transport().get_remote_server_key()
            if self.config.get('fingerprint') and fingerprint(key) != self.config['fingerprint']:
                raise ValueError('Изменился SSH-ключ выбранного сервера.')
            client.get_transport().set_keepalive(15)
            self.client = client
            self.root_user = self.command(['id', '-u']).strip() == '0'
        except paramiko.AuthenticationException:
            client.close()
            raise ValueError('Сервер отклонил SSH-логин, пароль или ключ.') from None
        except (paramiko.SSHException, OSError):
            client.close()
            raise ValueError('Не удалось установить проверенное SSH-подключение.') from None
        except ValueError:
            client.close()
            raise
        return self

    def command(self, arguments, *, root=False, input=None, timeout=40):
        if not self.client:
            raise ValueError('Сначала подключитесь к серверу.')
        command = shlex.join([str(v) for v in arguments])
        payload = input or b''
        if root and not self.root_user:
            if '\n' in self.sudo_password or '\r' in self.sudo_password:
                raise ValueError('Пароль sudo не должен содержать перенос строки.')
            command = sudo_command(arguments)
            payload = self.sudo_password.encode() + b'\n' + payload
        channel = self.client.get_transport().open_session(timeout=15)
        output, errors, deadline = bytearray(), bytearray(), time.monotonic() + timeout
        try:
            channel.settimeout(20)
            channel.exec_command(command)
            channel.sendall(payload)
            channel.shutdown_write()
            while True:
                if self.cancel and self.cancel.is_set():
                    raise InterruptedError('Ожидание отменено. Запущенная серверная операция продолжится.')
                if channel.recv_ready():
                    output.extend(channel.recv(65536))
                if channel.recv_stderr_ready():
                    errors.extend(channel.recv_stderr(65536))
                if len(output) + len(errors) > 2 * 1024**2:
                    raise ValueError('Ответ SSH-сервера слишком большой.')
                if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                    break
                if time.monotonic() >= deadline:
                    raise ValueError('SSH-сервер не ответил вовремя. Операцию можно продолжить повторным подключением.')
                time.sleep(0.03)
            if channel.recv_exit_status():
                try:
                    message = json.loads(output).get('error')
                except (ValueError, AttributeError):
                    message = None
                raise ValueError(message or ('Нужны права root или корректный пароль sudo.' if root else 'Команда SSH завершилась с ошибкой.'))
            return output.decode('utf-8')
        finally:
            channel.close()

    def close(self):
        if self.client:
            self.client.close()
            self.client = None
        self.password = self.sudo_password = self.key_passphrase = ''
