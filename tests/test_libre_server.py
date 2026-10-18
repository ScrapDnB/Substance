"""Exercise lifecycle, rollback, immutable operations and pinned SSH transport."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
from types import SimpleNamespace
from uuid import uuid4

import paramiko
import pytest

pytest.importorskip('fcntl', reason='The bundled server runtime targets Linux hosts')

from substance.libre_server import remote
from substance.server_ssh import SSHConnection, SSHHostKeyChanged, fingerprint, sudo_command

SPEC = importlib.util.spec_from_file_location('libre_remote', Path(__file__).resolve().parents[1] / 'substance/resources/libretranslate_server.py')
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
REAL_PROBE = runtime.probe
KEY = '12345678-1234-1234-1234-123456789abc'


@pytest.fixture
def host(tmp_path, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(runtime.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(runtime.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    snippet = tmp_path / 'dubbing-online.conf'
    snippet.write_text('location /v1/ { proxy_pass http://127.0.0.1:8000; }\n')
    original = snippet.read_bytes()
    old = {'Id': 'existing-id', 'State': {'Running': True}, 'Image': 'sha256:installed',
           'Config': {'Image': 'libretranslate/libretranslate:latest', 'Labels': {}},
           'Mounts': [{'Destination': '/home/libretranslate/.local'}],
           'HostConfig': {'RestartPolicy': {'Name': 'unless-stopped'},
                          'PortBindings': {'5000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '15000'}]}}}
    plan = {'domain': 'example.com', 'snippet': str(snippet), 'languages': 'en,ru,ja', 'port': 15000,
            'containerId': 'existing-id', 'exists': True, 'managed': False, 'dockerMissing': False,
            'dm': True, 'freeGB': 10.0, 'configHash': 'snapshot', 'url': 'https://example.com/libretranslate'}
    state = {'containers': {runtime.CONTAINER: old}, 'calls': [], 'plan': plan, 'fail': '', 'dmChecks': 0}
    def command(*args, **kwargs):
        state['calls'].append(args)
        name = args[-1]
        if args[:2] == ('docker', 'stop'):
            state['containers'][name]['State']['Running'] = False
        elif args[:2] == ('docker', 'rename'):
            state['containers'][args[3]] = state['containers'].pop(args[2])
        elif args[:2] == ('docker', 'run'):
            marker = args[args.index('--label') + 1].split('=', 1)[1]
            env = Path(args[args.index('--env-file') + 1]).read_text()
            assert 'LT_API_KEYS=true' in env and 'LT_REQ_LIMIT=0' in env and 'LT_LOAD_ONLY=en,ru,ja' in env
            assert '127.0.0.1:15000:5000' in args
            state['containers'][runtime.CONTAINER] = {'State': {'Running': True}, 'Config': {'Labels': {runtime.LABEL: marker}}}
        elif args[:2] == ('docker', 'exec'):
            return KEY
        elif args[:2] == ('docker', 'commit'):
            return 'sha256:snapshot'
        elif args[:2] == ('docker', 'rm'):
            state['containers'].pop(name)
        elif args[:2] == ('docker', 'start'):
            state['containers'][name]['State']['Running'] = True
        elif args == ('nginx', '-t') and state['fail'] == 'nginx' and runtime.BEGIN.encode() in snippet.read_bytes():
            state['fail'] = ''
            raise ValueError('nginx test failed')
        return ''
    def translation(url, key=''):
        if url.startswith('https://') and state['fail'] == 'https':
            return 503, {}
        if not key:
            return (200 if state['fail'] == 'anonymous' else 403), {}
        return 200, {'translatedText': 'Привет'}
    def healthy(domain):
        state['dmChecks'] += 1
        return state['fail'] != 'dm'
    monkeypatch.setattr(runtime, 'probe', lambda request: deepcopy(state['plan']))
    monkeypatch.setattr(runtime, 'parameters', lambda request: ('example.com', snippet, 'en,ru,ja'))
    monkeypatch.setattr(runtime, 'command', command)
    monkeypatch.setattr(runtime, 'inspect', lambda name: deepcopy(state['containers'].get(name)))
    monkeypatch.setattr(runtime, 'translation', translation)
    monkeypatch.setattr(runtime, 'dm_health', healthy)
    directory = tmp_path / str(uuid4())
    directory.mkdir()
    request = {'action': 'install', 'plan': deepcopy(plan)}
    return directory, snippet, original, request, state


@pytest.mark.parametrize('action', ['install', 'reinstall'])
def test_adoption_and_reinstallation_keep_models_and_do_not_touch_dm(host, action):
    directory, snippet, original, request, state = host
    request['action'] = action
    state['plan']['freeGB'] = 9.9  # ordinary disk fluctuations do not invalidate the plan
    result = runtime.mutate(directory, request)
    assert snippet.read_bytes().startswith(original.rstrip())
    assert 'proxy_pass http://127.0.0.1:15000/;' in snippet.read_text()
    assert 'proxy_pass http://127.0.0.1:8000;' in snippet.read_text()
    run = next(c for c in state['calls'] if c[:2] == ('docker', 'run'))
    assert '--volumes-from' in run and run[-1] == 'sha256:installed'
    assert not state['containers'][result['backup']]['State']['Running']
    assert result['key'] == KEY and result['modelsRetained']
    assert state['dmChecks'] == 1
    assert not any('prune' in call or 'compose' in call for call in state['calls'])
    # Credentials are absent from arguments, progress and the recovery plan.
    assert KEY not in json.dumps(state['calls'])
    assert KEY not in (directory / 'state.json').read_text()
    assert KEY not in (directory / 'recovery.json').read_text()


def test_fresh_install_downloads_image_and_uses_persistent_volumes(host):
    directory, snippet, original, request, state = host
    state['containers'].clear()
    state['plan'].update(exists=False, containerId='', dockerMissing=True)
    request['plan'] = deepcopy(state['plan'])
    runtime.mutate(directory, request)
    run = next(c for c in state['calls'] if c[:2] == ('docker', 'run'))
    assert runtime.MODELS + ':/home/libretranslate/.local' in run
    assert runtime.KEYS + ':/app/db' in run
    assert ('docker', 'pull', 'libretranslate/libretranslate:latest') in state['calls']
    assert any(c[:3] == ('env', 'DEBIAN_FRONTEND=noninteractive', 'apt-get') for c in state['calls'])


@pytest.mark.parametrize('failure', ['nginx', 'https', 'anonymous', 'dm'])
def test_failures_restore_live_container_restart_policy_and_nginx(host, failure):
    directory, snippet, original, request, state = host
    state['fail'] = failure
    with pytest.raises(ValueError):
        runtime.mutate(directory, request)
    assert snippet.read_bytes() == original
    assert list(state['containers']) == [runtime.CONTAINER]
    assert state['containers'][runtime.CONTAINER]['State']['Running']
    assert ('docker', 'update', '--restart=unless-stopped', runtime.CONTAINER) in state['calls']
    assert not (directory / 'result.json').exists()


def test_server_changes_refused_before_mutation(host):
    directory, snippet, original, request, state = host
    state['plan']['containerId'] = 'replaced-by-somebody'
    with pytest.raises(ValueError, match='изменилось'):
        runtime.mutate(directory, request)
    assert not state['calls'] and snippet.read_bytes() == original


def test_nginx_reload_delayed_route_is_retried_without_rolling_back(host, monkeypatch):
    directory, snippet, original, request, state = host
    initial = runtime.translation
    pending, observed = [404, 502], []
    def translation(url, key=''):
        if url.startswith('https://'):
            observed.append(bool(key))
            if pending:
                return pending.pop(0), {}
        return initial(url, key)
    monkeypatch.setattr(runtime, 'translation', translation)
    result = runtime.mutate(directory, request)
    assert result['key'] == KEY
    assert observed == [True, True, True, False]
    assert runtime.BEGIN in snippet.read_text()
    assert not any(call[:2] == ('docker', 'rm') for call in state['calls'])


def test_permanent_https_error_reports_status_and_restores_server(host, monkeypatch):
    directory, snippet, original, request, state = host
    initial = runtime.translation
    monkeypatch.setattr(runtime, 'translation', lambda url, key='': (404, {}) if url.startswith('https://') else initial(url, key))
    with pytest.raises(ValueError, match='HTTP 404.*маршрут') as failure:
        runtime.mutate(directory, request)
    assert KEY not in str(failure.value)
    assert snippet.read_bytes() == original
    assert list(state['containers']) == [runtime.CONTAINER]


@pytest.mark.parametrize('reason', ['tls', 'json', 'network'])
def test_https_diagnostics_distinguish_connection_failures_without_echoing_keys(host, monkeypatch, reason):
    from urllib.error import URLError
    import ssl
    exceptions = {'tls': URLError(ssl.SSLCertVerificationError('certificate ' + KEY)),
                  'json': ValueError('Response: ' + KEY), 'network': URLError(KEY)}
    def translation(*args, **kwargs):
        raise exceptions[reason]
    monkeypatch.setattr(runtime, 'translation', translation)
    with pytest.raises(ValueError) as failure:
        runtime.verify_https('https://example.com/libretranslate', KEY, wait_seconds=4)
    assert KEY not in str(failure.value)
    assert {'tls': 'TLS-сертификат', 'json': 'JSON', 'network': 'подключиться'}[reason] in str(failure.value)


def test_uninstall_only_removes_managed_route_and_stops_service(host):
    directory, snippet, original, request, state = host
    snippet.write_bytes(original + runtime.route('example.com', 15000).encode())
    state['plan']['managed'] = True
    request.update(action='uninstall', plan=deepcopy(state['plan']))
    result = runtime.mutate(directory, request)
    assert snippet.read_bytes() == original
    assert runtime.CONTAINER not in state['containers']
    assert not state['containers'][result['backup']]['State']['Running']
    assert not any(c[:2] in [('docker', 'volume'), ('docker', 'run')] for c in state['calls'])


def test_uninstall_foreign_route_refused(host):
    directory, snippet, original, request, state = host
    request['action'] = 'uninstall'
    with pytest.raises(ValueError, match='Удалять можно'):
        runtime.mutate(directory, request)
    assert not state['calls'] and snippet.read_bytes() == original


@pytest.mark.parametrize('failure', ['publicPort', 'dmNotReady', 'foreignImage'])
def test_real_probe_refuses_unsafe_host_before_changes(host, monkeypatch, failure):
    directory, snippet, original, request, state = host
    old = state['containers'][runtime.CONTAINER]
    if failure == 'publicPort':
        old['HostConfig']['PortBindings']['5000/tcp'][0]['HostIp'] = '0.0.0.0'
    elif failure == 'foreignImage':
        old['Config']['Image'] = 'postgres:16'
    else:
        state['fail'] = 'dm'
    base_command = runtime.command
    def command(*args, **kwargs):
        if args == ('nginx', '-T'):
            return 'server_name example.com; include ' + str(snippet) + ';'
        return base_command(*args, **kwargs)
    monkeypatch.setattr(runtime, 'command', command)
    monkeypatch.setattr(runtime.shutil, 'which', lambda name: '/usr/bin/' + name)
    with pytest.raises(ValueError):
        REAL_PROBE(request)
    assert snippet.read_bytes() == original
    assert not any(c[:2] in [('docker', 'run'), ('docker', 'stop'), ('docker', 'update')] for c in state['calls'])


def test_dispatch_is_immutable_and_duplicate_start_never_spawns_twice(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime, 'ROOT', tmp_path)
    monkeypatch.setattr(runtime, 'ensure_root', lambda: None)
    monkeypatch.setattr(runtime.os, 'kill', lambda *args: (_ for _ in ()).throw(ProcessLookupError()))
    spawned = []
    def spawn(*args, **kwargs):
        spawned.append((args, kwargs))
        return SimpleNamespace(pid=999999)
    monkeypatch.setattr(runtime.subprocess, 'Popen', spawn)
    request = {'id': str(uuid4()), 'action': 'install', 'plan': {}}
    runtime.dispatch('start', request)
    runtime.dispatch('start', request)
    assert len(spawned) == 1 and spawned[0][1]['start_new_session']
    with pytest.raises(ValueError, match='другим запросом'):
        runtime.dispatch('start', {**request, 'action': 'uninstall'})
    assert runtime.dispatch('status', {'id': request['id']})['phase'] == 'error'
    assert runtime.dispatch('status', {'id': str(uuid4())})['phase'] == 'missing'


def test_remote_payload_is_uploaded_and_checksummed_over_stdin():
    captured = {}
    def command(args, **kwargs):
        captured.update(args=args, **kwargs)
        return '{"exists":true}'
    assert remote(SimpleNamespace(command=command), 'probe', {'domain': 'example.com'})['exists']
    assert captured['root'] and captured['args'][:2] == ['python3', '-c']
    payload = json.loads(captured['input'])
    assert payload['request'] == {'domain': 'example.com'} and payload['sha256']
    assert 'example.com' not in shlex.join(captured['args'])


def test_host_key_pin_is_enforced_and_changed_key_not_trusted(tmp_path, monkeypatch):
    first, changed = paramiko.RSAKey.generate(2048), paramiko.RSAKey.generate(2048)
    config = {'host': 'example.com', 'ssh_user': 'root', 'ssh_port': 22}
    connection = SSHConnection(config, tmp_path)
    key = {'key_type': first.get_name(), 'key': first.get_base64(), 'fingerprint': fingerprint(first)}
    connection.trust_key(key)
    assert (tmp_path / 'known_hosts').stat().st_mode & 0o777 == 0o600
    transport = SimpleNamespace(get_security_options=lambda: SimpleNamespace(key_types=('ssh-rsa',)),
        start_client=lambda **kwargs: None, get_remote_server_key=lambda: changed, close=lambda: None)
    monkeypatch.setattr('substance.server_ssh.socket.create_connection', lambda *a, **k: None)
    monkeypatch.setattr(paramiko, 'Transport', lambda *a, **k: transport)
    with pytest.raises(SSHHostKeyChanged) as exc:
        connection.inspect_key()
    assert exc.value.host_key['fingerprint'] == fingerprint(changed)
    assert connection._known_keys()['ssh-rsa'] == first


def test_sudo_consumes_password_when_nopasswd_leaves_stdin_untouched(tmp_path):
    sudo = tmp_path / 'sudo'
    sudo.write_text('#!/bin/sh\nif [ "$1" = "-S" ]; then cat >/dev/null; exit 0; fi\nshift; shift; exec "$@"\n')
    sudo.chmod(0o700)
    import os
    result = subprocess.run(sudo_command(['python3', '-c', 'import sys;print(sys.stdin.read())']), shell=True,
        input='secret-sudo-password\n{"hello":1}', text=True, capture_output=True,
        env={**os.environ, 'PATH': str(tmp_path) + ':' + os.environ['PATH']}, timeout=5)
    assert result.returncode == 0 and result.stdout.strip() == '{"hello":1}'
