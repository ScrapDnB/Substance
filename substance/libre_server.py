"""Desktop LibreTranslate SSH wizard; server operations outlive the UI connection."""
import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
import hashlib
import json
import os
from pathlib import Path
import threading
from uuid import uuid4

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .server_ssh import SSHConnection, SSHHostKeyChanged, ssh_parameters


# Uploaded via stdin to verified SSH, then copied into a root-owned directory.
# Source, checksum and request never appear in the process command line.
BOOTSTRAP = '''import base64,hashlib,json,os,pathlib,stat,subprocess,sys,tempfile
os.umask(0o077)
p=json.load(sys.stdin)
r=pathlib.Path('/var/lib/substance-libretranslate')
r.mkdir(mode=0o700,parents=True,exist_ok=True)
s=r.lstat()
assert stat.S_ISDIR(s.st_mode) and s.st_uid==0, 'Unsafe installer directory'
r.chmod(0o700)
b=base64.b64decode(p['source']); h=hashlib.sha256(b).hexdigest()
assert h==p['sha256'], 'Installer checksum mismatch'
f=r/('runtime-'+h+'.py')
if not f.exists():
 fd,t=tempfile.mkstemp(dir=r)
 with os.fdopen(fd,'wb') as w: w.write(b); w.flush(); os.fsync(w.fileno())
 os.replace(t,f)
assert not f.is_symlink() and f.stat().st_uid==0 and f.read_bytes()==b, 'Unsafe installer source'
v=subprocess.run([sys.executable,str(f),p['action']],input=json.dumps(p['request']).encode())
sys.exit(v.returncode)
'''


def private_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name('.' + path.name + '-' + uuid4().hex)
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            temporary.chmod(0o600)
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        with suppress(FileNotFoundError):
            temporary.unlink()


def remote(connection, action, request):
    source = (Path(__file__).parent / 'resources/libretranslate_server.py').read_bytes()
    payload = {'source': base64.b64encode(source).decode(), 'sha256': hashlib.sha256(source).hexdigest(),
               'action': action, 'request': request}
    answer = json.loads(connection.command(['python3', '-c', BOOTSTRAP], root=True,
                                          input=json.dumps(payload).encode(), timeout=60))
    if not isinstance(answer, dict):
        raise ValueError('Некорректный ответ установщика.')
    return answer


class LibreServerController(QObject):
    changed = Signal()
    openRequested = Signal()
    _reply = Signal(str, object)

    def __init__(self, assistance):
        super().__init__(assistance)
        self.assistance = assistance
        self.directory = assistance.backend.data_dir / 'libre-server'
        self._profile = {'host': '', 'ssh_user': 'root', 'ssh_port': 22, 'key_file': '',
                         'domain': '', 'snippet': '/etc/nginx/snippets/dubbing-online.conf', 'languages': 'en,ru,ja'}
        try:
            saved = json.loads(assistance.backend.settings.value('libreServer/profile', '{}'))
            self._profile.update({k: v for k, v in saved.items() if k in self._profile or k == 'fingerprint'})
        except (ValueError, TypeError, AttributeError):
            pass
        self._pending = None
        try:
            value = json.loads((self.directory / 'pending.json').read_text())
            if isinstance(value, dict) and value.get('id'):
                self._pending = value
                self._profile = value['profile']
        except (OSError, ValueError, KeyError, TypeError):
            pass
        self._secrets = {}
        self._key = {}
        self._plan = {}
        self._step, self._busy = 0, False
        self._status = 'Есть незавершённая операция. Подключитесь для проверки результата.' if self._pending else ''
        self._closed = False
        self._cancel = threading.Event()
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='libre-server')
        self._reply.connect(self._received)
        self._poll = QTimer(self, interval=5000, singleShot=True)
        self._poll.timeout.connect(self._poll_status)

    @Property('QVariantMap', notify=changed)
    def profile(self):
        return dict(self._profile)

    @Property('QVariantMap', notify=changed)
    def hostKey(self):
        return {k: v for k, v in self._key.items() if k != 'key'}

    @Property('QVariantMap', notify=changed)
    def plan(self):
        return dict(self._plan)

    @Property(int, notify=changed)
    def step(self):
        return self._step

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(bool, notify=changed)
    def pending(self):
        return bool(self._pending)

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Slot()
    def open(self):
        self.openRequested.emit()

    @Slot()
    def chooseKey(self):
        path, _ = QFileDialog.getOpenFileName(None, 'Закрытый SSH-ключ', str(Path.home() / '.ssh'), 'Все файлы (*)')
        if path:
            self.setField('key_file', path)

    @Slot(str, 'QVariant')
    def setField(self, name, value):
        if self._busy or self._step != 0 or (self._pending and name != 'key_file'):
            return
        if name not in ('host', 'ssh_user', 'ssh_port', 'key_file', 'domain', 'snippet', 'languages'):
            return
        if name == 'ssh_port':
            try:
                value = int(value)
            except (ValueError, TypeError):
                return
        elif not isinstance(value, str) or len(value) > 1024:
            return
        else:
            value = value.strip()
        if self._profile.get(name) == value:
            return
        self._profile[name] = value
        self._plan, self._key = {}, {}
        if name in ('host', 'ssh_user', 'ssh_port', 'key_file'):
            self._secrets.clear()
        if name in ('host', 'ssh_port'):
            self._profile.pop('fingerprint', None)
        if self._pending:
            # A moved private key must not strand a resumable operation. Its
            # server, user and immutable server-side request remain pinned.
            self._pending['profile'] = dict(self._profile)
            try:
                private_json(self.directory / 'pending.json', self._pending)
            except OSError:
                self._status = 'Не удалось сохранить новый путь к SSH-ключу.'
        self.changed.emit()

    def _submit(self, kind, callback):
        if self._busy or self._closed:
            return
        self._busy = True
        self.changed.emit()
        def work():
            try:
                return callback()
            except SSHHostKeyChanged as exc:
                return {'hostKeyChanged': exc.host_key, 'error': str(exc)}
            except (ValueError, InterruptedError) as exc:
                return {'error': str(exc)}
            except Exception:
                return {'error': 'Не удалось подключиться. Проверьте SSH-доступ, Python 3 и права root / sudo.'}
        future = self._executor.submit(work)
        def completed(result):
            if not self._closed:
                with suppress(RuntimeError):
                    self._reply.emit(kind, result.result())
        future.add_done_callback(completed)

    def _connection(self):
        return SSHConnection(dict(self._profile), self.directory, cancel=self._cancel, **self._secrets)

    def _call(self, action, request):
        connection = self._connection()
        try:
            connection.connect()
            return remote(connection, action, request)
        finally:
            connection.close()

    @Slot(str, str, str)
    def connectToServer(self, password, passphrase, sudo_password):
        if self._busy or self._closed:
            return
        try:
            ssh_parameters(self._profile)
        except ValueError as exc:
            self._status = str(exc)
            self.changed.emit()
            return
        self._secrets = {'password': password, 'key_passphrase': passphrase, 'sudo_password': sudo_password}
        self._status = 'Проверка SSH-ключа сервера…'
        def inspect():
            connection = self._connection()
            try:
                return connection.inspect_key()
            finally:
                connection.close()
        self._submit('key', inspect)

    @Slot()
    def confirmHostKey(self):
        if self._busy or not self._key or self._key.get('changed'):
            return
        connection = self._connection()
        try:
            connection.trust_key(self._key)
            self._profile['fingerprint'] = self._key['fingerprint']
            self._save_profile()
        except Exception:
            self._status = 'Не удалось сохранить проверенный ключ сервера.'
            self.changed.emit()
            return
        finally:
            connection.close()
        self._status = 'Проверка Docker, nginx, HTTPS и существующего контейнера…'
        if self._pending:
            self._step = 3
            self._poll_status()
        else:
            self._submit('probe', lambda: self._call('probe', dict(self._profile)))

    def _save_profile(self):
        self.assistance.backend.settings.setValue('libreServer/profile', json.dumps(self._profile))

    @Slot(str)
    def execute(self, action):
        if self._busy or self._pending or self._step != 2 or action not in ('install', 'reinstall', 'uninstall'):
            return
        if action == 'uninstall' and not (self._plan.get('exists') and self._plan.get('managed')):
            return
        request = {k: self._profile[k] for k in ('domain', 'snippet', 'languages')}
        request.update(id=str(uuid4()), action=action, plan=dict(self._plan))
        self._pending = {'id': request['id'], 'profile': dict(self._profile), 'request': request}
        try:
            private_json(self.directory / 'pending.json', self._pending)
        except OSError:
            self._pending = None
            self._status = 'Не удалось сохранить номер операции на этом компьютере. Сервер не изменён.'
            self.changed.emit()
            return
        self._step, self._status = 3, 'Отправка операции на сервер…'
        self._submit('status', lambda: self._call('start', request))

    @Slot()
    def reconnect(self):
        if self._busy:
            return
        self._poll.stop()
        self._step = 0
        self._status = 'Укажите пароль или ключ и подключитесь снова. Операция на сервере продолжает выполняться.' if self._pending else ''
        self.changed.emit()

    def _poll_status(self):
        if self._pending and not self._busy and not self._closed:
            identifier = self._pending['id']
            self._submit('status', lambda: self._call('status', {'id': identifier}))

    def _forget_pending(self):
        with suppress(FileNotFoundError):
            (self.directory / 'pending.json').unlink()
        self._pending = None

    @Slot(str, object)
    def _received(self, kind, value):
        if self._closed:
            return
        self._busy = False
        if value.get('error'):
            self._status = value['error']
            if value.get('hostKeyChanged'):
                self._key = value['hostKeyChanged']
                self._step = 1
            self.changed.emit()
            return
        if kind == 'key':
            self._key, self._step = value, 1
            self._status = 'Сверьте отпечаток с консолью или панелью вашего VPS-провайдера.'
            if value.get('known'):
                self.confirmHostKey()
        elif kind == 'probe':
            self._plan, self._step = value, 2
            self._status = 'Проверка пройдена. Выберите действие и подтвердите его ниже.'
        elif kind == 'status':
            self._status = value.get('message', '')
            if value['phase'] == 'complete':
                identifier = self._pending['id']
                self._submit('result', lambda: self._call('result', {'id': identifier}))
            elif value['phase'] == 'error':
                self._step = 4
                self._forget_pending()
                self._secrets.clear()
            elif value['phase'] == 'missing':
                # Retry the *same* immutable request, including its UUID.
                request = dict(self._pending['request'])
                self._submit('status', lambda: self._call('start', request))
            else:
                self._step = 3
                self._poll.start()
        elif kind == 'result':
            if value['action'] != 'uninstall':
                self.assistance.setOption('libreUrl', value['url'])
                self.assistance.setOption('provider', 'libre')
                self.assistance.saveKey(value['key'])
                self._status = 'Готово. HTTPS-адрес и API-ключ добавлены в настройки. ' + self.assistance.keyMessage
            else:
                self._status = 'LibreTranslate остановлен, маршрут HTTPS удалён. Модели и копия контейнера сохранены для восстановления.'
                # Remove only the credential for the endpoint actually removed.
                name = 'libre:' + value['url']
                self.assistance._keys.pop(name, None)
                with suppress(Exception):
                    self.assistance.vault.put(name, '')
                self.assistance.preferencesChanged.emit()
            self._forget_pending()
            self._secrets.clear()
            self._step = 4
        self.changed.emit()

    def shutdown(self):
        self._closed = True
        self._poll.stop()
        self._cancel.set()
        self._secrets.clear()
        self._executor.shutdown(wait=False, cancel_futures=True)
