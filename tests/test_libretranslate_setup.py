"""Host setup plan is tested with an isolated Docker/nginx model, never production."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location('libre_setup', Path(__file__).resolve().parents[1] / 'scripts/configure_libretranslate_https.py')
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)


@pytest.fixture
def host(tmp_path, monkeypatch):
    snippet = tmp_path / 'dubbing-online.conf'
    original = b'location /v1/ { proxy_pass http://127.0.0.1:8000; }\n'
    snippet.write_bytes(original)
    state = {'containers': {'substance-libretranslate': {
        'State': {'Running': True}, 'HostConfig': {'PortBindings': {'5000/tcp': [{'HostIp': '127.0.0.1', 'HostPort': '15000'}]},
            'RestartPolicy': {'Name': 'unless-stopped', 'MaximumRetryCount': 0}},
        'Image': 'sha256:original', 'Mounts': [{'Destination': '/home/libretranslate/.local'}],
        'Config': {'Env': ['LT_LOAD_ONLY=en,ru,ja'], 'Cmd': None, 'Labels': {}}}},
        'calls': [], 'anonymous': 403, 'reject_nginx_once': False}
    def command(*args, **kwargs):
        state['calls'].append(args)
        if args == ('nginx', '-T'):
            return 'server_name scrap.lain.ch;\ninclude ' + str(snippet) + ';'
        if args == ('nginx', '-t'):
            if state['reject_nginx_once'] and b'/libretranslate/' in snippet.read_bytes():
                state['reject_nginx_once'] = False
                raise RuntimeError('Invalid nginx configuration')
        if args[:2] == ('docker', 'stop'):
            state['containers'][args[-1]]['State']['Running'] = False
        if args[:2] == ('docker', 'rename'):
            old, new = args[2:]
            state['containers'][new] = state['containers'].pop(old)
        if args[:2] == ('docker', 'run'):
            name = args[args.index('--name') + 1]
            marker = args[args.index('--label') + 1].split('=', 1)[1]
            state['containers'][name] = {'Config': {'Labels': {'substance.https-setup': marker}}, 'State': {'Running': True}}
            env = Path(args[args.index('--env-file') + 1]).read_text()
            assert 'LT_API_KEYS=true' in env and 'LT_REQ_LIMIT=0' in env and 'LT_LOAD_ONLY=en,ru,ja' in env
            assert '--volumes-from' in args
        if args[:2] == ('docker', 'exec'):
            return '12345678-1234-1234-1234-123456789abc'
        if args[:2] == ('docker', 'commit'):
            return 'sha256:snapshot'
        if args[:2] == ('docker', 'rm'):
            state['containers'].pop(args[-1])
        if args[:2] == ('docker', 'start'):
            state['containers'][args[-1]]['State']['Running'] = True
        return ''
    monkeypatch.setattr(setup, 'command', command)
    monkeypatch.setattr(setup, 'inspect', lambda name: deepcopy(state['containers'][name]))
    monkeypatch.setattr(setup, 'health', lambda domain: True)
    monkeypatch.setattr(setup, 'translation', lambda url, key='': (200, {'translatedText': 'Привет'}) if key else (state['anonymous'], {}))
    return snippet, original, state


def test_setup_keeps_original_container_models_and_dm_routes(host, capsys):
    snippet, original, state = host
    setup.configure('substance-libretranslate', 'scrap.lain.ch', snippet)
    assert snippet.read_bytes().startswith(original)
    assert 'proxy_pass http://127.0.0.1:15000/;' in snippet.read_text()
    backups = [name for name in state['containers'] if '-before-https-' in name]
    assert len(backups) == 1 and not state['containers'][backups[0]]['State']['Running']
    assert not any(call[:2] == ('docker', 'commit') for call in state['calls'])
    assert any(call == ('systemctl', 'reload', 'nginx') for call in state['calls'])
    assert 'https://scrap.lain.ch/libretranslate' in capsys.readouterr().out


@pytest.mark.parametrize('failure', ['anonymous', 'nginx'])
def test_failed_auth_or_nginx_test_restores_old_container_and_config(host, failure):
    snippet, original, state = host
    if failure == 'anonymous':
        state['anonymous'] = 200
    else:
        state['reject_nginx_once'] = True
    with pytest.raises(RuntimeError):
        setup.configure('substance-libretranslate', 'scrap.lain.ch', snippet)
    assert snippet.read_bytes() == original
    assert list(state['containers']) == ['substance-libretranslate']
    assert state['containers']['substance-libretranslate']['State']['Running']
    assert any(call[:3] == ('docker', 'update', '--restart=unless-stopped') for call in state['calls'])


def test_models_in_container_layer_are_snapshotted(host):
    snippet, _, state = host
    state['containers']['substance-libretranslate']['Mounts'] = []
    setup.configure('substance-libretranslate', 'scrap.lain.ch', snippet)
    assert ('docker', 'commit', 'substance-libretranslate') in state['calls']
    run = next(call for call in state['calls'] if call[:2] == ('docker', 'run'))
    assert run[-1] == 'sha256:snapshot'


def test_public_binding_is_refused_before_any_mutation(host):
    snippet, original, state = host
    state['containers']['substance-libretranslate']['HostConfig']['PortBindings']['5000/tcp'][0]['HostIp'] = '0.0.0.0'
    with pytest.raises(RuntimeError, match='127.0.0.1'):
        setup.configure('substance-libretranslate', 'scrap.lain.ch', snippet)
    assert not any(call[:2] in [('docker', 'stop'), ('docker', 'run')] for call in state['calls'])
    assert snippet.read_bytes() == original
