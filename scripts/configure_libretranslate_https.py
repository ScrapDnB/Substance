#!/usr/bin/env python3
"""Run on the Docker/nginx host, as root. Keeps the old container for rollback."""
import argparse
from contextlib import suppress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def command(*args, timeout=90):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f'{args[0]}: {result.stderr.strip()[-1500:]}')
    return result.stdout.strip()


def inspect(name):
    return json.loads(command('docker', 'inspect', name))[0]


def translation(url, key=''):
    body = {'q': 'Hello, world!', 'source': 'en', 'target': 'ru', 'format': 'text'}
    if key:
        body['api_key'] = key
    request = Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    try:
        with urlopen(request, timeout=10) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        exc.close()
        return exc.code, {}


def health(domain):
    with urlopen('https://' + domain + '/health/ready', timeout=10) as response:
        return json.load(response).get('status') == 'ready'


def write_config(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        shutil.copystat(path, temporary)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def nginx_block(domain, port):
    return f'''
# BEGIN Substance LibreTranslate HTTPS
location ^~ /libretranslate/ {{
    if ($host != {domain}) {{ return 404; }}
    if ($scheme != https) {{ return 404; }}
    client_max_body_size 128k;
    proxy_pass http://127.0.0.1:{port}/;
    proxy_http_version 1.1;
    proxy_set_header Connection "";
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $remote_addr;
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
}}
# END Substance LibreTranslate HTTPS
'''


def configure(container, domain, snippet, wait_seconds=600):
    if not re.fullmatch(r'[a-zA-Z0-9.-]+', domain):
        raise RuntimeError('Некорректное имя домена.')
    snippet = Path(snippet)
    original = snippet.read_bytes()
    if b'/libretranslate/' in original:
        raise RuntimeError('Маршрут /libretranslate/ уже есть. Повторная установка остановлена.')
    command('nginx', '-t')
    config = command('nginx', '-T')
    if f'include {snippet};' not in config or domain not in config:
        raise RuntimeError('Ожидаемое подключение nginx snippet к домену не найдено.')
    if not health(domain):
        raise RuntimeError('Dubbing Manager не отвечает ready. Настройка остановлена до изменений.')
    old = inspect(container)
    if not old['State']['Running']:
        raise RuntimeError('Контейнер LibreTranslate должен быть запущен.')
    bindings = old['HostConfig']['PortBindings'].get('5000/tcp') or []
    if len(bindings) != 1 or bindings[0]['HostIp'] != '127.0.0.1':
        raise RuntimeError('Ожидался один порт LibreTranslate, доступный только на 127.0.0.1.')
    port = int(bindings[0]['HostPort'])
    if port == 8000:
        raise RuntimeError('Порт 8000 зарезервирован для Dubbing Manager.')
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime()) + '-' + str(os.getpid())
    backup_container = container + '-before-https-' + stamp
    backup_file = snippet.with_name(snippet.name + '.before-libretranslate-' + stamp)
    restart = old['HostConfig']['RestartPolicy']['Name'] or 'no'
    retries = old['HostConfig']['RestartPolicy'].get('MaximumRetryCount', 0)
    if restart == 'on-failure' and retries:
        restart += ':' + str(retries)
    image = old['Image']
    # --volumes-from preserves mounted model directories. If models live in
    # the writable container layer, snapshot that layer before replacing it.
    if not any(m['Destination'] == '/home/libretranslate/.local' for m in old['Mounts']):
        print('Сохранение моделей из файловой системы контейнера…', flush=True)
        image = command('docker', 'commit', container, timeout=600)
    renamed = stopped = attempted = route_written = False
    updated = original + nginx_block(domain, port).encode()
    shutil.copy2(snippet, backup_file)
    try:
        with tempfile.TemporaryDirectory(prefix='libretranslate-https-') as temporary:
            env = dict(item.split('=', 1) for item in old['Config']['Env'] if '=' in item)
            env.update(LT_API_KEYS='true', LT_REQ_LIMIT='0', LT_API_KEYS_DB_PATH='/app/db/api_keys.db',
                       LT_THREADS='1', LT_UPDATE_MODELS='false')
            if any('\n' in value or '\r' in value for value in env.values()):
                raise RuntimeError('Многострочная переменная контейнера не поддерживается.')
            env_path = Path(temporary) / 'container.env'
            env_path.write_text(''.join(f'{key}={value}\n' for key, value in env.items()))
            env_path.chmod(0o600)
            command('docker', 'update', '--restart=no', container)
            stopped = True
            command('docker', 'stop', '--time', '60', container)
            command('docker', 'rename', container, backup_container)
            renamed = True
            attempted = True
            command('docker', 'run', '-d', '--name', container, '--restart', 'unless-stopped',
                    '--label', 'substance.https-setup=' + stamp,
                    '--volumes-from', backup_container,
                    '-v', container + '-keys:/app/db',
                    '-p', f'127.0.0.1:{port}:5000', '--env-file', str(env_path), image,
                    *(old['Config'].get('Cmd') or []))
        key = command('docker', 'exec', container, '/app/venv/bin/python', '-c',
                      'from libretranslate.api_keys import Database; '
                      'print(Database("/app/db/api_keys.db").add(120, char_limit=12000)[0])').splitlines()[-1]
        if not re.fullmatch(r'[0-9a-fA-F-]{36}', key):
            raise RuntimeError('Не удалось получить API-ключ.')
        local = f'http://127.0.0.1:{port}/translate'
        print('Ожидание запуска LibreTranslate и проверка перевода…', flush=True)
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                status, result = translation(local, key)
                if status == 200 and result.get('translatedText'):
                    break
            except (OSError, URLError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise RuntimeError('LibreTranslate не запустился вовремя. Проверьте docker logs.')
            time.sleep(2)
        status, _ = translation(local)
        if status not in (400, 401, 403, 429):
            raise RuntimeError('Отказ в переводе без API-ключа не подтверждён.')
        if snippet.read_bytes() != original:
            raise RuntimeError('Конфигурация nginx изменилась во время настройки. Запись отменена.')
        write_config(snippet, updated)
        route_written = True
        command('nginx', '-t')
        command('systemctl', 'reload', 'nginx')
        public = 'https://' + domain + '/libretranslate/translate'
        status, result = translation(public, key)
        if status != 200 or not result.get('translatedText'):
            raise RuntimeError('Проверка перевода через HTTPS не прошла.')
        status, _ = translation(public)
        if status not in (400, 401, 403, 429) or not health(domain):
            raise RuntimeError('Проверка ключей или готовности Dubbing Manager не прошла.')
    except BaseException:
        print('Ошибка. Восстановление прежней конфигурации…', file=sys.stderr)
        rollback_errors = []
        def recover(*args):
            try:
                return command(*args)
            except Exception as exc:
                rollback_errors.append(str(exc))
        if route_written and snippet.read_bytes() == updated:
            try:
                write_config(snippet, original)
                command('nginx', '-t')
                command('systemctl', 'reload', 'nginx')
            except Exception as exc:
                rollback_errors.append(str(exc))
        elif route_written:
            rollback_errors.append('Nginx изменён другим процессом; автоматическое восстановление файла пропущено.')
        if attempted:
            with suppress(Exception):
                if inspect(container)['Config']['Labels'].get('substance.https-setup') == stamp:
                    recover('docker', 'rm', '-f', container)
        if renamed:
            recover('docker', 'rename', backup_container, container)
        if stopped:
            recover('docker', 'start', container)
        recover('docker', 'update', '--restart=' + restart, container)
        for error in rollback_errors:
            print('Откат требует проверки: ' + error, file=sys.stderr)
        raise
    print('\nГотово. Перевод через HTTPS работает; отказ без ключа проверен.')
    print('Сервис в Substance: LibreTranslate')
    print('Адрес: https://' + domain + '/libretranslate')
    print('API-ключ: ' + key)
    print('Резервный контейнер: ' + backup_container)
    print('Резервная конфигурация nginx: ' + str(backup_file))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--domain', required=True)
    parser.add_argument('--container', default='substance-libretranslate')
    parser.add_argument('--nginx-snippet', default='/etc/nginx/snippets/dubbing-online.conf')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Запустите от root или через sudo.')
    for executable in ('docker', 'nginx', 'systemctl'):
        if not shutil.which(executable):
            parser.error('Не найдена команда ' + executable)
    os.umask(0o077)
    try:
        configure(args.container, args.domain, args.nginx_snippet)
    except Exception as exc:
        print('Настройка не завершена: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
