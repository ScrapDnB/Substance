#!/usr/bin/env python3
"""Root-side LibreTranslate operations. Standard library only; no desktop imports.

Requests arrive on stdin, generated credentials stay in root-only result files.
Operations run independently of the SSH connection; each UUID is dispatched once.
"""
from contextlib import suppress
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import stat
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID

ROOT = Path('/var/lib/substance-libretranslate')
CONTAINER = 'substance-libretranslate'
MODELS = CONTAINER + '-models'
KEYS = CONTAINER + '-keys'
LABEL = 'substance.libretranslate'
BEGIN = '# BEGIN Substance LibreTranslate HTTPS'
END = '# END Substance LibreTranslate HTTPS'


def atomic(path, value):
    """Private state/result and replacement configs are committed atomically."""
    data = json.dumps(value, ensure_ascii=False).encode() if isinstance(value, dict) else value
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists():
            shutil.copystat(path, temporary)
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def command(*args, timeout=90, check=True):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode and check:
        # Docker/env/API output may contain secrets. Never return raw stderr.
        raise ValueError('Не выполнена серверная команда: ' + Path(args[0]).name + ' ' + (args[1] if len(args) > 1 else '') + '.')
    return result.stdout.strip() if result.returncode == 0 else ''


def inspect(name):
    result = command('docker', 'inspect', name, check=False)
    return json.loads(result)[0] if result else None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def translation(url, key=''):
    body = {'q': 'Hello', 'source': 'en', 'target': 'ru', 'format': 'text'}
    if key:
        body['api_key'] = key
    request = Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    try:
        with build_opener(NoRedirect()).open(request, timeout=15) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        exc.close()
        return exc.code, {}


def dm_health(domain):
    with build_opener(NoRedirect()).open('https://' + domain + '/health/ready', timeout=15) as response:
        return json.load(response).get('status') == 'ready'


def parameters(request):
    domain = str(request.get('domain', '')).lower().strip()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]{0,250}[a-z0-9])?', domain) or '..' in domain:
        raise ValueError('Укажите доменное имя существующего HTTPS-сайта без https:// и пути.')
    snippet = Path(request.get('snippet') or '/etc/nginx/snippets/dubbing-online.conf')
    if not snippet.is_absolute() or not str(snippet.resolve()).startswith('/etc/nginx/'):
        raise ValueError('Конфигурационный файл должен находиться в /etc/nginx/.')
    languages = request.get('languages', 'en,ru,ja')
    if not isinstance(languages, str) or not re.fullmatch(r'[a-z]{2,3}(?:,[a-z]{2,3}){0,29}', languages):
        raise ValueError('Языки задаются кодами через запятую, например en,ru,ja.')
    if not {'en', 'ru'} <= set(languages.split(',')):
        raise ValueError('Оставьте en и ru для проверки работы сервера; можно добавить другие языки.')
    return domain, snippet, languages


def without_route(text):
    if BEGIN not in text and END not in text:
        if re.search(r'location\s+[^\n{]*?/libretranslate', text):
            raise ValueError('Путь /libretranslate уже занят чужой конфигурацией.')
        return text
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.index(END) < text.index(BEGIN):
        raise ValueError('Повреждён блок LibreTranslate в nginx. Нужна проверка конфигурации.')
    return re.sub(re.escape(BEGIN) + r'.*?' + re.escape(END) + r'\n?', '', text, flags=re.S)


def route(domain, port):
    return f'''{BEGIN}
location ^~ /libretranslate/ {{
    if ($host != {domain}) {{ return 404; }}
    if ($scheme != https) {{ return 404; }}
    client_max_body_size 128k;
    proxy_pass http://127.0.0.1:{port}/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
}}
{END}
'''


def probe(request):
    domain, snippet, languages = parameters(request)
    if not shutil.which('nginx') or not snippet.is_file() or snippet.stat().st_size > 2 * 1024**2:
        raise ValueError('Нужен nginx с действующим HTTPS-сайтом. Для сервера Dubbing Manager оставьте стандартный файл nginx.')
    text = snippet.read_text()
    without_route(text)
    command('nginx', '-t')
    nginx = command('nginx', '-T')
    if f'include {snippet};' not in nginx or not re.search(r'\b' + re.escape(domain) + r'(?:\s|;)', nginx):
        raise ValueError('Этот файл не подключён к указанному HTTPS-сайту nginx.')
    # Preserve the live readiness check on Dubbing Manager hosts.
    dm = '/health/ready' in text or 'dubbing-online' in str(snippet)
    if dm and not dm_health(domain):
        raise ValueError('Dubbing Manager сейчас не отвечает ready. Установка остановлена до изменений.')
    docker = bool(shutil.which('docker'))
    if docker:
        command('docker', 'info')
    old = inspect(CONTAINER) if docker else None
    port = 15000
    if old:
        # Do not accidentally take over another image under a familiar name.
        image = (old['Config'].get('Image') or '').lower()
        labels = old['Config'].get('Labels') or {}
        if 'libretranslate' not in image and LABEL not in labels and 'substance.https-setup' not in labels:
            raise ValueError('Имя контейнера занято другим приложением. Контейнер не изменён.')
        bindings = old['HostConfig']['PortBindings'].get('5000/tcp') or []
        if len(bindings) != 1 or bindings[0]['HostIp'] != '127.0.0.1':
            raise ValueError('Существующий LibreTranslate должен слушать только 127.0.0.1.')
        port = int(bindings[0]['HostPort'])
    if port in (22, 80, 443, 8000) or not 1024 <= port <= 65535:
        raise ValueError('Порт LibreTranslate конфликтует с другим сервисом.')
    if not old:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
            except OSError:
                raise ValueError('Локальный порт 15000 занят. Освободите его перед установкой.') from None
    usage = shutil.disk_usage('/var/lib')
    distro = Path('/etc/os-release').read_text() if Path('/etc/os-release').exists() else ''
    if not docker and not (shutil.which('apt-get') and re.search(r'(debian|ubuntu)', distro, re.I)):
        raise ValueError('Для этой системы сначала установите Docker. Автоустановка поддерживает Debian и Ubuntu.')
    return {'domain': domain, 'snippet': str(snippet), 'languages': languages, 'port': port,
            'containerId': old['Id'] if old else '', 'exists': bool(old), 'managed': BEGIN in text,
            'dockerMissing': not docker, 'dm': dm, 'freeGB': round(usage.free / 1024**3, 1),
            'configHash': hashlib.sha256(text.encode()).hexdigest(),
            'url': 'https://' + domain + '/libretranslate'}


def ensure_root():
    if os.geteuid() != 0:
        raise ValueError('Нужны права root или sudo.')
    ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = ROOT.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
        raise ValueError('Небезопасный каталог состояния установщика.')
    ROOT.chmod(0o700)


def operation_dir(value):
    try:
        identifier = str(UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Некорректный номер операции.') from None
    return ROOT / identifier


def state(directory, phase, message, **extra):
    atomic(directory / 'state.json', {'phase': phase, 'message': message, **extra})


def restart_policy(old):
    value = old['HostConfig']['RestartPolicy']
    policy = value.get('Name') or 'no'
    return policy + (':' + str(value['MaximumRetryCount']) if policy == 'on-failure' and value.get('MaximumRetryCount') else '')


def reload_nginx():
    command('nginx', '-t')
    command('systemctl', 'reload', 'nginx')


def https_failure(status):
    details = {404: 'маршрут /libretranslate/ не найден в HTTPS-сайте nginx',
               502: 'nginx не может подключиться к LibreTranslate',
               503: 'сервис временно недоступен', 504: 'nginx не дождался ответа LibreTranslate',
               401: 'HTTPS-сайт требует дополнительную авторизацию',
               403: 'HTTPS-сайт или сервис отклонил запрос с API-ключом',
               429: 'превышен лимит запросов'}
    if status in (301, 302, 303, 307, 308):
        return f'HTTP {status}: HTTPS-сайт перенаправляет запрос на другой адрес'
    if status == 200:
        return 'HTTP 200: в ответе отсутствует результат перевода'
    return f'HTTP {status}' + (': ' + details[status] if status in details else '')


def connection_failure(exc):
    reason = exc.reason if isinstance(exc, URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError):
        return 'не удалось проверить TLS-сертификат HTTPS-сайта'
    if isinstance(reason, ssl.SSLError):
        return 'не удалось установить защищённое TLS-соединение'
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return 'HTTPS-сайт не ответил вовремя'
    if isinstance(exc, ValueError):
        return 'HTTPS-сайт вернул некорректный JSON вместо ответа API'
    return 'не удалось подключиться к HTTPS-сайту с сервера'


def verify_https(url, key, wait_seconds=60):
    """nginx reload is asynchronous; wait for the new route before rollback.

    Never include response bodies or exception strings: they may echo the key.
    An endpoint accepting anonymous translations is rolled back immediately.
    """
    deadline = time.monotonic() + wait_seconds
    while True:
        try:
            status, translated = translation(url + '/translate', key)
        except (OSError, URLError, ValueError) as exc:
            last_error = connection_failure(exc)
        else:
            last_error = https_failure(status)
            if status == 200 and isinstance(translated, dict) and translated.get('translatedText'):
                try:
                    anonymous, _ = translation(url + '/translate')
                except (OSError, URLError, ValueError) as exc:
                    last_error = 'проверка доступа без ключа: ' + connection_failure(exc)
                else:
                    if anonymous in (400, 401, 403, 429):
                        return
                    if anonymous == 200:
                        raise ValueError('Публичный сервер не требует API-ключ. Публикация отменена.')
                    last_error = 'проверка доступа без ключа: ' + https_failure(anonymous)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ValueError('Перевод через HTTPS не работает: ' + last_error + '. Адрес: ' + url + '.')
        time.sleep(min(2, remaining))


def mutate(directory, request):
    plan = probe(request)
    stable = ('domain', 'snippet', 'languages', 'port', 'containerId', 'exists', 'managed', 'dockerMissing', 'dm', 'configHash')
    if any(plan[k] != request['plan'].get(k) for k in stable):
        raise ValueError('Состояние сервера изменилось после проверки. Проверьте сервер заново.')
    action = request['action']
    if action not in ('install', 'reinstall', 'uninstall'):
        raise ValueError('Неизвестное действие.')
    if action != 'uninstall' and plan['freeGB'] < 2:
        raise ValueError('Для установки нужно хотя бы 2 ГБ свободного места в /var/lib.')
    if action == 'uninstall' and (not plan['exists'] or not plan['managed']):
        raise ValueError('Удалять можно LibreTranslate, подключённый этим мастером или установщиком Substance.')
    domain, snippet, languages = parameters(request)
    original = snippet.read_bytes()
    updated = without_route(original.decode()).encode()
    if action != 'uninstall':
        updated = updated.rstrip(b'\n') + b'\n\n' + route(domain, plan['port']).encode()
    atomic(directory / 'nginx-before.conf', original)
    old = inspect(CONTAINER) if plan['exists'] else None
    backup = CONTAINER + '-backup-' + directory.name
    atomic(directory / 'recovery.json', {'container': CONTAINER, 'backup': backup, 'snippet': str(snippet),
           'restart': restart_policy(old) if old else '', 'wasRunning': bool(old and old['State']['Running'])})
    renamed = touched = route_written = attempted = False
    try:
        if plan['dockerMissing']:
            state(directory, 'running', 'Установка Docker из репозитория системы…')
            command('apt-get', 'update', timeout=600)
            command('env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get', 'install', '-y', 'docker.io', timeout=1200)
            command('systemctl', 'enable', '--now', 'docker')
        image = old['Image'] if old else 'libretranslate/libretranslate:latest'
        if action != 'uninstall':
            state(directory, 'running', 'Загрузка образа LibreTranslate…')
            if not old:
                command('docker', 'pull', image, timeout=1200)
            if old and not any(m['Destination'] == '/home/libretranslate/.local' for m in old['Mounts']):
                state(directory, 'running', 'Сохранение моделей из существующего контейнера…')
                # A snapshot preserves models stored in the container layer.
                image = command('docker', 'commit', CONTAINER, timeout=600)
        if old:
            state(directory, 'running', 'Сохранение прежнего контейнера для отката…')
            command('docker', 'update', '--restart=no', CONTAINER)
            touched = True
            command('docker', 'stop', '--time', '60', CONTAINER)
            command('docker', 'rename', CONTAINER, backup)
            renamed = True
        if action != 'uninstall':
            state(directory, 'running', 'Запуск LibreTranslate и загрузка языковых моделей…')
            env = {'LT_LOAD_ONLY': languages, 'LT_THREADS': '1', 'LT_API_KEYS': 'true', 'LT_REQ_LIMIT': '0',
                   'LT_API_KEYS_DB_PATH': '/app/db/api_keys.db', 'LT_UPDATE_MODELS': 'false'}
            envfile = directory / 'container.env'
            atomic(envfile, ''.join(f'{k}={v}\n' for k, v in env.items()).encode())
            mounts = ['--volumes-from', backup] if old else ['-v', MODELS + ':/home/libretranslate/.local']
            # Reuse an existing keys mount without stacking two at /app/db.
            if not old or not any(m['Destination'] == '/app/db' for m in old['Mounts']):
                mounts += ['-v', KEYS + ':/app/db']
            attempted = True
            command('docker', 'run', '-d', '--name', CONTAINER, '--restart', 'unless-stopped',
                    '--label', LABEL + '=' + directory.name, *mounts,
                    '-p', f"127.0.0.1:{plan['port']}:5000", '--env-file', str(envfile), image)
            # First-run models can take a long time. Poll until both the DB
            # and the translation service are ready; never expose raw logs.
            deadline, key = time.monotonic() + 1800, ''
            while time.monotonic() < deadline:
                try:
                    if not key:
                        key = command('docker', 'exec', CONTAINER, '/app/venv/bin/python', '-c',
                            'from libretranslate.api_keys import Database; '
                            'print(Database("/app/db/api_keys.db").add(120, char_limit=12000)[0])').splitlines()[-1]
                        if not re.fullmatch(r'[a-fA-F0-9-]{36}', key):
                            raise ValueError('Не удалось создать API-ключ.')
                    status, translated = translation(f"http://127.0.0.1:{plan['port']}/translate", key)
                    if status == 200 and translated.get('translatedText'):
                        break
                except (ValueError, OSError, URLError, IndexError):
                    pass
                time.sleep(3)
            else:
                raise ValueError('LibreTranslate не запустился за 30 минут. Прежняя конфигурация будет восстановлена.')
            if translation(f"http://127.0.0.1:{plan['port']}/translate")[0] not in (400, 401, 403, 429):
                raise ValueError('Сервер принимает запросы без API-ключа. Публикация отменена.')
        state(directory, 'running', 'Проверка и применение маршрута HTTPS…')
        if snippet.read_bytes() != original:
            raise ValueError('Файл nginx изменён другим процессом. Автоматическая запись отменена.')
        atomic(snippet, updated)
        route_written = True
        reload_nginx()
        if action != 'uninstall':
            verify_https(plan['url'], key)
        if plan['dm'] and not dm_health(domain):
            raise ValueError('Проверка готовности Dubbing Manager не прошла.')
        # Commit before destructive cleanup. No model volumes are deleted.
        result = {'action': action, 'url': plan['url'], 'key': key if action != 'uninstall' else '',
                  'backup': backup if old else '', 'modelsRetained': True}
        atomic(directory / 'result.json', result)
    except BaseException:
        failures = []
        def recover(callback):
            try:
                callback()
            except Exception:
                failures.append(True)
        state(directory, 'running', 'Восстановление прежнего контейнера и nginx…')
        if route_written:
            if snippet.read_bytes() == updated:
                recover(lambda: atomic(snippet, original))
                recover(reload_nginx)
            else:
                failures.append(True)
        if attempted:
            current = inspect(CONTAINER)
            if current and (current['Config'].get('Labels') or {}).get(LABEL) == directory.name:
                recover(lambda: command('docker', 'rm', '-f', CONTAINER))
        if renamed:
            recover(lambda: command('docker', 'rename', backup, CONTAINER))
        if touched:
            if old['State']['Running']:
                recover(lambda: command('docker', 'start', CONTAINER))
            recover(lambda: command('docker', 'update', '--restart=' + restart_policy(old), CONTAINER))
        if failures:
            raise ValueError('Откат завершён не полностью. Копия nginx и параметры восстановления: ' + str(directory)) from None
        raise
    # Stopped backups deliberately remain available for rollback/recovery.
    return result


def worker(directory):
    ensure_root()
    try:
        with (ROOT / 'mutation.lock').open('a') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('На сервере уже выполняется другая операция LibreTranslate.') from None
            request = json.loads((directory / 'request.json').read_text())
            state(directory, 'running', 'Повторная проверка сервера…', pid=os.getpid())
            mutate(directory, request)
            state(directory, 'complete', 'LibreTranslate удалён. Модели сохранены.' if request['action'] == 'uninstall'
                  else 'LibreTranslate работает через HTTPS. Подключение настроено автоматически.')
    except Exception as exc:
        message = str(exc) if isinstance(exc, ValueError) else 'Серверная операция прервана. Проверьте доступность сервера и повторите проверку.'
        state(directory, 'error', message)


def dispatch(action, request):
    ensure_root()
    if action == 'probe':
        return probe(request)
    directory = operation_dir(request.get('id'))
    if action == 'start':
        # Serialise duplicate submissions and persist the exact request before
        # spawn. An uncertain result never silently creates a second operation.
        with (ROOT / 'dispatch.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if directory.exists():
                if json.loads((directory / 'request.json').read_text()) != request:
                    raise ValueError('Номер операции уже занят другим запросом.')
            else:
                directory.mkdir(mode=0o700)
                atomic(directory / 'request.json', request)
                state(directory, 'starting', 'Операция принята сервером…')
                with (directory / 'worker.log').open('wb') as log:
                    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'worker', directory.name],
                                               stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
                atomic(directory / 'pid.json', {'pid': process.pid})
        return dispatch('status', {'id': directory.name})
    if not directory.is_dir():
        return {'phase': 'missing', 'message': 'Операция ещё не была принята сервером.'}
    if action == 'result':
        if json.loads((directory / 'state.json').read_text())['phase'] != 'complete':
            raise ValueError('Операция ещё не завершена.')
        return json.loads((directory / 'result.json').read_text())
    if action == 'status':
        current = json.loads((directory / 'state.json').read_text())
        if current['phase'] in ('starting', 'running'):
            try:
                pid = json.loads((directory / 'pid.json').read_text())['pid']
                os.kill(pid, 0)
                # PID reuse after reboot must not pretend the worker is alive.
                cmdline = Path(f'/proc/{pid}/cmdline').read_bytes()
                if directory.name.encode() not in cmdline:
                    raise ProcessLookupError()
            except (OSError, KeyError):
                current = {'phase': 'error', 'message': 'Сервер перезапускался или процесс остановлен. Копии для восстановления: ' + str(directory)}
        return current
    raise ValueError('Неизвестная команда установщика.')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        if sys.argv[1] == 'worker':
            worker(operation_dir(sys.argv[2]))
        else:
            print(json.dumps(dispatch(sys.argv[1], json.load(sys.stdin)), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, ValueError) else 'Не удалось выполнить команду установщика.'}, ensure_ascii=False))
        sys.exit(1)
