import json
import os
import gzip
from io import BytesIO
from pathlib import Path
import threading

import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import load_document
from substance.language_assistance import install_dictionary
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


class Vault:
    def __init__(self):
        self.values = {}
    def get(self, name):
        return self.values.get(name, '')
    def put(self, name, value):
        self.values[name] = value


def wait_for(condition):
    for _ in range(150):
        if condition():
            return
        QTest.qWait(20)
    assert condition()


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    QQuickStyle.setStyle('Fusion')
    b = Backend()
    b.language_assistance.vault = Vault()
    b._set_document(load_document(ROOT / 'substance/resources/example.ass'), '')
    b.setMode('translation')
    messages = []
    handler = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
        assert engine.rootObjects(), messages
        w = engine.rootObjects()[0]
        QTest.qWait(100)
        yield b, w, tmp_path
    finally:
        b.shutdown()
        shiboken6.delete(engine)
        qInstallMessageHandler(handler)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'is not a function', 'Non-existent'))], messages


def test_settings_instructions_and_secret_persistence(ui):
    b, w, tmp_path = ui
    a = b.language_assistance
    a.openSettings()
    QTest.qWait(60)
    assert w.findChild(QObject, 'languageSettingsPane').property('visible')
    instructions = w.findChild(QObject, 'assistanceProviderInstructions')
    assert 'F0' in instructions.property('text')
    a.saveKey('private-api-key')
    assert a.hasKey and a.vault.values['azure'] == 'private-api-key'
    a.setOption('target', 'ja')
    b.settings.sync()
    assert 'private-api-key' not in (tmp_path / 'settings.ini').read_text()
    a.setOption('provider', 'libre')
    assert not a.hasKey
    a.setOption('libreUrl', 'http://localhost:5001')
    a.saveKey('private-local-key')
    a.setOption('libreUrl', 'http://localhost:5002')
    assert not a.hasKey
    assert 'localhost:5000' in instructions.property('text')
    a.setOption('provider', 'deepl')
    assert 'DeepL API' in instructions.property('text')
    a.saveKey('')
    assert not a.hasKey


def test_real_editor_selection_dictionary_and_phrase_without_document_edits(ui, monkeypatch):
    b, w, tmp_path = ui
    a = b.language_assistance
    source = tmp_path / 'words.jsonl'
    source.write_text(json.dumps({'word': 'Hello', 'lang_code': 'en', 'lang': 'English', 'pos': 'intj',
        'senses': [{'glosses': ['A greeting.'], 'examples': [{'text': 'Hello, friend!'}]}]}) + '\n')
    install_dictionary(source, a.directory / 'en.sqlite', 'en')
    calls = []
    def translated(texts, source, target, config, key, context=''):
        calls.append((texts, context))
        return ['Привет' if t.startswith('Hello') else 'Приветствие.' for t in texts], 'en'
    monkeypatch.setattr('substance.language_controller.translate', translated)
    editor = w.findChild(QObject, 'originalEditor')
    editor.setProperty('text', 'Hello wonderful world')
    editor.select(0, 5)
    before = b.editor.document.to_dict()
    wait_for(lambda: bool(a.result.get('complete')))
    assert a.result['translation'] == 'Привет'
    assert a.result['entries'][0]['senses'][0]['translatedDefinition'] == 'Приветствие.'
    assert w.findChild(QObject, 'languageTranslation').property('text') == 'Привет'
    if os.environ.get('SUBSTANCE_LANGUAGE_SCREENSHOTS'):
        output = Path(os.environ['SUBSTANCE_LANGUAGE_SCREENSHOTS'])
        output.mkdir(parents=True, exist_ok=True)
        QTest.qWait(60)
        assert w.grabWindow().save(str(output / 'word.png'))
    editor.select(0, 21)
    wait_for(lambda: a.result.get('kind') == 'phrase' and a.result.get('complete'))
    assert not a.result['entries']
    assert calls[-1][0] == ['Hello wonderful world']
    assert b.editor.document.to_dict() == before
    b.appearance.setValue('translation', 'videoVisible', False)
    QTest.qWait(40)
    assert w.findChild(QObject, 'languagePane').property('visible')
    editor.deselect()
    assert not a.query and not a.result


def test_stale_inflight_reply_never_replaces_new_selection(ui, monkeypatch):
    b, _, _ = ui
    a = b.language_assistance
    started, release = threading.Event(), threading.Event()
    def translated(texts, *args, **kwargs):
        if texts == ['old']:
            started.set()
            release.wait(3)
        return [text.upper() for text in texts], 'en'
    monkeypatch.setattr('substance.language_controller.translate', translated)
    a.selectText('old', 0, 3, 'original')
    a.lookup()
    wait_for(started.is_set)
    a.selectText('new sentence', 0, 12, 'original')
    a.lookup()
    wait_for(lambda: a.result.get('translation') == 'NEW SENTENCE')
    release.set()
    QTest.qWait(80)
    assert a.result['text'] == 'new sentence'
    b.navigate(1)
    assert not a.query and not a.result


def test_manual_mode_and_connection_check(ui, monkeypatch):
    b, w, _ = ui
    a = b.language_assistance
    calls = []
    def translated(texts, *args, **kwargs):
        calls.append(texts)
        return ['Привет'], 'en'
    monkeypatch.setattr('substance.language_controller.translate', translated)
    a.setOption('automatic', False)
    a.selectText('Hello', 0, 5, 'original')
    QTest.qWait(450)
    assert not calls and not a.result
    w.findChild(QObject, 'languageLookupButton').clicked.emit()
    wait_for(lambda: a.result.get('complete'))
    assert calls == [['Hello']]
    a.checkConnection()
    wait_for(lambda: not a.checking)
    assert 'Подключение работает' in a.checkStatus
    assert a.query == 'Hello'


def test_async_import_and_dictionary_survives_missing_api_key(ui):
    b, _, tmp_path = ui
    a = b.language_assistance
    source = tmp_path / 'dictionary.jsonl'
    source.write_text(json.dumps({'word': 'charge', 'lang_code': 'en', 'pos': 'noun',
        'senses': [{'glosses': ['A fee.']}]}))
    a.installFile(str(source), 'en')
    wait_for(lambda: not a.installing)
    assert 'Словарь установлен' in a.installStatus and a.installed
    a.selectText('charge', 0, 6, 'original')
    a.lookup()
    wait_for(lambda: a.result.get('complete'))
    assert a.result['entries'][0]['senses'][0]['definition'] == 'A fee.'
    assert 'API-ключ' in a.result['error']
    assert not a.result['dictionaryMissing']


def test_downloader_streams_and_indexes_a_dictionary_pack(ui, monkeypatch):
    b, _, _ = ui
    a = b.language_assistance
    archive = gzip.compress(json.dumps({'word': 'hello', 'lang_code': 'en', 'pos': 'intj',
        'senses': [{'glosses': ['A greeting.']}]}).encode())
    def opened(request, timeout):
        assert request.full_url.endswith('/simple/simple-extract.jsonl.gz')
        return BytesIO(archive)
    monkeypatch.setattr('substance.language_controller.network_open', opened)
    a.downloadDictionary('simple')
    wait_for(lambda: not a.installing)
    assert 'Словарь установлен' in a.installStatus
    assert (a.directory / 'simple.sqlite').is_file()
    assert not list(a.directory.glob('*.gz'))
    a.selectText('hello', 0, 5, 'original')
    a.lookup()
    wait_for(lambda: a.result.get('complete'))
    assert a.result['entries'][0]['url'] == 'https://simple.wiktionary.org/wiki/hello'


def test_language_layout_fits_small_window_and_settings_scroll(ui, monkeypatch):
    b, w, _ = ui
    a = b.language_assistance
    monkeypatch.setattr('substance.language_controller.translate', lambda texts, *args, **kwargs: (['Перевод длинного выделенного предложения.'], 'en'))
    b.appearance.setValue('general', 'uiScale', 125)
    w.resize(980, 650)
    a.selectText('A selected sentence', 0, 19, 'original')
    a.lookup()
    wait_for(lambda: a.result.get('complete'))
    panel = w.findChild(QObject, 'languagePane')
    assert panel.width() > 200 and panel.height() >= 140
    assert panel.findChild(QObject, 'languageLookupButton').width() <= panel.width()
    assert not w.grabWindow().isNull()
    a.openSettings()
    QTest.qWait(80)
    settings = w.findChild(QObject, 'languageSettingsPane')
    assert settings.property('contentHeight') > settings.height()
    a.setOption('provider', 'libre')
    assert 'LT_LOAD_ONLY' in a.libreCommand
    assert '127.0.0.1:5000:5000' in a.libreCommand
    if os.environ.get('SUBSTANCE_LANGUAGE_SCREENSHOTS'):
        output = Path(os.environ['SUBSTANCE_LANGUAGE_SCREENSHOTS'])
        output.mkdir(parents=True, exist_ok=True)
        dialog = w.findChild(QObject, 'settingsDialog')
        QTest.qWait(100)
        assert dialog.grabWindow().save(str(output / 'settings.png'))
        dialog.close()
        w.resize(1280, 850)
        b.appearance.setValue('general', 'uiScale', 100)
        b.appearance.setValue('translation', 'videoVisible', False)
        a.selectText('A selected sentence', 0, 19, 'original')
        a.lookup()
        wait_for(lambda: a.result.get('complete'))
        QTest.qWait(100)
        assert w.grabWindow().save(str(output / 'panel.png'))


def test_local_only_keeps_dictionary_and_never_reads_vault_or_calls_translator(ui, monkeypatch):
    b, w, tmp_path = ui
    a = b.language_assistance
    source = tmp_path / 'local.jsonl'
    source.write_text(json.dumps({'word': 'hello', 'lang_code': 'en', 'pos': 'intj',
        'senses': [{'glosses': ['A greeting.'], 'translations': [{'lang_code': 'ru', 'word': 'привет'}]}]}))
    install_dictionary(source, a.directory / 'en.sqlite', 'en')
    def forbidden(*args, **kwargs):
        pytest.fail('local-only mode accessed translation or credential storage')
    monkeypatch.setattr(a.vault, 'get', forbidden)
    monkeypatch.setattr('substance.language_controller.translate', forbidden)
    a.setOption('localOnly', True)
    a.openSettings()
    QTest.qWait(40)
    assert w.findChild(QObject, 'assistanceLocalOnly').property('checked')
    for name in ('assistanceOnlineSettings', 'assistanceOnlineInstructions', 'assistanceProvider', 'assistanceServerWizard'):
        assert not w.findChild(QObject, name).property('visible')
    a.selectText('hello', 0, 5, 'original')
    a.lookup()
    wait_for(lambda: a.result.get('complete'))
    assert a.result['entries'][0]['senses'][0]['definition'] == 'A greeting.'
    assert not a.result['error'] and not a.result['translation'] and not a.providerTitle
    a.checkConnection()
    assert not a.checking
    w.findChild(QObject, 'settingsDialog').close()
    QTest.qWait(30)
    assert not w.findChild(QObject, 'languageProvider').property('visible')
    assert w.findChild(QObject, 'languageQuery').property('visible')
    assert w.findChild(QObject, 'languageLookupButton').property('text') == 'Найти'
    a.selectText('hello world', 0, 11, 'original')
    a.lookup()
    wait_for(lambda: a.result.get('kind') == 'phrase' and a.result.get('complete'))
    assert w.findChild(QObject, 'languageLocalPhraseHint').property('visible')
    assert json.loads(b.settings.value('languageAssistance/v1'))['localOnly'] is True


def test_local_only_toggle_discards_inflight_translation_and_skips_definition_requests(ui, monkeypatch):
    b, _, tmp_path = ui
    a = b.language_assistance
    source = tmp_path / 'local.jsonl'
    source.write_text(json.dumps({'word': 'hello', 'lang_code': 'en', 'pos': 'intj',
        'senses': [{'glosses': ['A greeting.']}]}))
    install_dictionary(source, a.directory / 'en.sqlite', 'en')
    entered, release = threading.Event(), threading.Event()
    calls = []
    def translator(texts, *args, **kwargs):
        calls.append(texts)
        entered.set()
        release.wait(3)
        return ['OLD TRANSLATION'], 'en'
    monkeypatch.setattr('substance.language_controller.translate', translator)
    a.selectText('hello', 0, 5, 'original')
    a.lookup()
    wait_for(entered.is_set)
    a.setOption('localOnly', True)
    a.lookup()
    wait_for(lambda: a.result.get('complete'))
    release.set()
    QTest.qWait(100)
    assert calls == [['hello']]
    assert not a.result['translation']
    assert 'translatedDefinition' not in a.result['entries'][0]['senses'][0]


def test_server_wizard_reviews_trust_and_resumes_same_operation_without_leaking_secrets(ui, monkeypatch):
    b, w, tmp_path = ui
    a = b.language_assistance
    manager = a.serverManager
    calls, trusted, authenticated = [], [], []
    class Connection:
        def __init__(self, config, directory, **secrets):
            self.config = config
        def inspect_key(self):
            return {'key_type': 'ssh-ed25519', 'key': 'private-host-key-bytes', 'fingerprint': 'SHA256:verified', 'known': False}
        def trust_key(self, value):
            trusted.append(value['fingerprint'])
        def connect(self):
            authenticated.append(True)
        def close(self):
            pass
    plan = {'url': 'https://example.com/libretranslate', 'exists': True, 'managed': False,
            'port': 15000, 'freeGB': 10.0, 'dockerMissing': False}
    failures = [True]
    def remote(connection, action, request):
        calls.append((action, request))
        if action == 'probe':
            return plan
        if action == 'start':
            return {'phase': 'running', 'message': 'Installing'}
        if action == 'status':
            if failures:
                failures.pop()
                raise ValueError('SSH connection interrupted')
            return {'phase': 'complete', 'message': 'Ready'}
        if action == 'result':
            return {'url': plan['url'], 'key': 'generated-api-secret', 'action': 'install'}
        assert False
    monkeypatch.setattr('substance.libre_server.SSHConnection', Connection)
    monkeypatch.setattr('substance.libre_server.remote', remote)
    # Exercise the real QML window and its controller, with an isolated SSH peer.
    a.setOption('provider', 'libre')
    a.openSettings()
    manager.open()
    QTest.qWait(50)
    wizard = w.findChild(QObject, 'libreServerWizard')
    assert wizard.isVisible() and wizard.isModal() and wizard.width() <= 650
    for name, value in [('host', 'example.com'), ('domain', 'example.com'), ('key_file', '/path/to/key')]:
        manager.setField(name, value)
    if os.environ.get('SUBSTANCE_LANGUAGE_SCREENSHOTS'):
        output = Path(os.environ['SUBSTANCE_LANGUAGE_SCREENSHOTS'])
        output.mkdir(parents=True, exist_ok=True)
        QTest.qWait(60)
        assert wizard.grabWindow().save(str(output / 'server-connection.png'))
    manager.connectToServer('ssh-private-password', 'key-private-passphrase', 'sudo-private-password')
    wait_for(lambda: not manager.busy and manager.step == 1)
    assert not authenticated and not calls and 'key' not in manager.hostKey
    manager.confirmHostKey()
    wait_for(lambda: not manager.busy and manager.step == 2)
    assert trusted == ['SHA256:verified']
    assert not w.findChild(QObject, 'libreExecute').property('enabled')
    if os.environ.get('SUBSTANCE_LANGUAGE_SCREENSHOTS'):
        output = Path(os.environ['SUBSTANCE_LANGUAGE_SCREENSHOTS'])
        QTest.qWait(60)
        assert wizard.grabWindow().save(str(output / 'server-review.png'))
    manager.execute('install')
    wait_for(lambda: not manager.busy and manager.step == 3)
    manager._poll.stop()
    journal = tmp_path / 'libre-server/pending.json'
    saved = json.loads(journal.read_text())
    for secret in ('ssh-private-password', 'key-private-passphrase', 'sudo-private-password', 'generated-api-secret'):
        assert secret not in journal.read_text()
    assert saved['profile']['fingerprint'] == 'SHA256:verified'
    # Closing the window does not cancel the remote operation.
    wizard.close()
    manager._poll_status()
    wait_for(lambda: not manager.busy)
    assert manager.pending and 'interrupted' in manager.status
    manager.reconnect()
    manager.setField('key_file', '/moved/ssh-key')
    assert json.loads(journal.read_text())['profile']['key_file'] == '/moved/ssh-key'
    assert manager.profile['fingerprint'] == 'SHA256:verified'
    manager.connectToServer('ssh-private-password', '', '')
    wait_for(lambda: not manager.busy and manager.step == 1)
    manager.confirmHostKey()
    wait_for(lambda: not manager.busy and manager.step == 4)
    assert not manager.pending and not journal.exists()
    assert a.config['libreUrl'] == plan['url'] and a.config['provider'] == 'libre'
    assert a.vault.values['libre:' + plan['url']] == 'generated-api-secret'
    assert len([call for call in calls if call[0] == 'start']) == 1
    assert {req['id'] for action, req in calls if action in ('start', 'status', 'result')} == {saved['id']}
    b.settings.sync()
    settings = (tmp_path / 'settings.ini').read_text()
    assert not any(secret in settings for secret in ('ssh-private-password', 'key-private-passphrase', 'sudo-private-password', 'generated-api-secret'))
