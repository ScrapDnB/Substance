"""Selection-driven language assistance. No document mutation or credential serialization."""
from collections import OrderedDict
from contextlib import closing
from copy import deepcopy
import json
import sqlite3
import threading
from urllib.request import Request
from urllib.error import URLError

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFileDialog

from .language_assistance import (AssistanceError, LANGUAGES, PACKS, PROVIDERS, clean_text,
                                  endpoint, install_dictionary, lookup_dictionary, network_open,
                                  selected_plain_text, translate, word_selection)

DEFAULTS = {'provider': 'azure', 'source': 'auto', 'target': 'ru', 'automatic': True,
            'localOnly': False,
            'context': True, 'translateDefinitions': True, 'azureRegion': '',
            'deeplPlan': 'auto', 'libreUrl': 'http://localhost:5000'}
LIBRE_COMMAND = 'docker run -d --name substance-libretranslate -p 127.0.0.1:5000:5000 -e LT_LOAD_ONLY=en,ru libretranslate/libretranslate'
GREETINGS = dict(zip((code for code, _ in LANGUAGES),
    ['Hello', 'Привет', 'こんにちは', '안녕하세요', '你好', 'Hallo', 'Bonjour', 'Hola',
     'Ciao', 'Olá', 'Привіт', 'Cześć', 'Merhaba', 'مرحبا', 'Hallo']))


class ApiVault:
    SERVICE = 'com.scrapdnb.substance.translation'

    def _backend(self):
        import sys
        if sys.platform == 'darwin':
            from keyring.backends.macOS import Keyring
            return Keyring()
        if sys.platform == 'win32':
            from keyring.backends.Windows import WinVaultKeyring
            return WinVaultKeyring()
        from keyring.backends.SecretService import Keyring
        return Keyring()

    def get(self, name):
        return self._backend().get_password(self.SERVICE, name) or ''

    def put(self, name, value):
        backend = self._backend()
        if value:
            backend.set_password(self.SERVICE, name, value)
        elif backend.get_password(self.SERVICE, name):
            backend.delete_password(self.SERVICE, name)


class WorkSignals(QObject):
    result = Signal(int, object)
    done = Signal(int)
    progress = Signal(str)


class Work(QRunnable):
    def __init__(self, serial, callback):
        super().__init__()
        self.serial, self.callback = serial, callback
        self.signals = WorkSignals()
        self.cancelled = threading.Event()

    def run(self):
        try:
            if self.cancelled.is_set():
                return
            result = self.callback(self)
            if not self.cancelled.is_set():
                self.signals.result.emit(self.serial, result)
        except Exception as exc:
            if not self.cancelled.is_set():
                # Only our own safe error messages may reach the UI.
                message = str(exc) if isinstance(exc, AssistanceError) else 'Не удалось обработать данные. Проверьте файл или настройки.'
                self.signals.result.emit(self.serial, {'error': message})
        finally:
            self.signals.done.emit(self.serial)


class LanguageController(QObject):
    changed = Signal()
    preferencesChanged = Signal()
    settingsRequested = Signal()

    def __init__(self, backend, vault=None):
        super().__init__(backend)
        self.backend = backend
        self.directory = backend.data_dir / 'dictionaries'
        self.vault = vault or ApiVault()
        try:
            saved = json.loads(backend.settings.value('languageAssistance/v1', '{}'))
        except (TypeError, ValueError):
            saved = {}
        self._config = dict(DEFAULTS)
        if isinstance(saved, dict):
            for name, value in saved.items():
                if name in DEFAULTS and self._valid(name, value):
                    self._config[name] = value
        self._keys = {}
        self._key_message = ''
        self._serial = 0
        self._jobs = {}
        self._install = None
        self._install_status = ''
        self._checking = False
        self._check_status = ''
        self._closed = False
        self._selection = None
        self._result = {}
        self._busy = False
        self._cache = OrderedDict()
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._import_pool = QThreadPool(self)
        self._import_pool.setMaxThreadCount(1)
        self._timer = QTimer(self, interval=400, singleShot=True)
        self._timer.timeout.connect(self.lookup)
        backend.currentChanged.connect(self.reset)
        backend.documentReplaced.connect(self.reset)
        backend.appearance.changed.connect(self._appearance_changed)
        from .libre_server import LibreServerController
        self._server = LibreServerController(self)

    @Property(QObject, constant=True)
    def serverManager(self):
        return self._server

    @Slot()
    def _appearance_changed(self):
        if not self.backend.appearance.translation['contextVisible']:
            self.reset()

    @staticmethod
    def _valid(name, value):
        if name not in DEFAULTS:
            return False
        if isinstance(DEFAULTS[name], bool):
            return type(value) is bool
        if not isinstance(value, str) or len(value) > 500:
            return False
        if name == 'provider':
            return value in PROVIDERS
        if name in ('source', 'target'):
            return value in dict(LANGUAGES) or (name == 'source' and value == 'auto')
        if name == 'deeplPlan':
            return value in ('auto', 'free', 'pro')
        if name == 'azureRegion':
            return not value or (value.isascii() and value.isalnum())
        if name == 'libreUrl':
            try:
                endpoint(value)
            except ValueError:
                return False
        return True

    @Property('QVariantMap', notify=preferencesChanged)
    def config(self):
        return dict(self._config)

    @Property('QVariantList', constant=True)
    def languages(self):
        return [{'code': code, 'title': title} for code, title in LANGUAGES]

    @Property('QVariantList', constant=True)
    def packs(self):
        return [{'id': key, **value} for key, value in PACKS.items()]

    @Property(str, notify=preferencesChanged)
    def providerTitle(self):
        return '' if self._config['localOnly'] else PROVIDERS[self._config['provider']]

    @Property('QVariantMap', notify=changed)
    def result(self):
        return self._result

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def query(self):
        return self._selection['text'] if self._selection else ''

    @Property(str, notify=preferencesChanged)
    def keyMessage(self):
        return self._key_message

    def _vault_name(self, provider):
        # Keys for self-hosted servers belong to that exact endpoint.
        return provider + (':' + self._config['libreUrl'] if provider == 'libre' else '')

    def _key(self):
        name = self._vault_name(self._config['provider'])
        if name not in self._keys:
            try:
                self._keys[name] = self.vault.get(name)
            except Exception:
                self._keys[name] = ''
        return self._keys[name]

    @Property(bool, notify=preferencesChanged)
    def hasKey(self):
        return not self._config['localOnly'] and bool(self._key())

    @Property(bool, notify=changed)
    def installing(self):
        return self._install is not None

    @Property(str, notify=changed)
    def installStatus(self):
        return self._install_status

    @Property(str, notify=changed)
    def checkStatus(self):
        return self._check_status

    @Property(bool, notify=changed)
    def checking(self):
        return self._checking

    @Property('QStringList', notify=changed)
    def installed(self):
        result = []
        for path in sorted(self.directory.glob('*.sqlite')):
            try:
                with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                    meta = dict(db.execute('SELECT key, value FROM metadata'))
                result.append(f"{path.stem} · {int(meta['count']):,} статей · пояснения: {meta['language']}")
            except (sqlite3.Error, ValueError, KeyError):
                continue
        return result

    @Slot(str, 'QVariant')
    def setOption(self, name, value):
        if self._closed:
            return
        if not self._valid(name, value):
            self._key_message = ('Укажите корректный адрес LibreTranslate без /translate, ключа и параметров.' if name == 'libreUrl'
                                 else 'Некорректное значение настройки. Проверьте введённые данные.')
            self.preferencesChanged.emit()
            return
        if self._config[name] == value:
            return
        self._config[name] = value.strip() if isinstance(value, str) else value
        self.backend.settings.setValue('languageAssistance/v1', json.dumps(self._config))
        self._cache.clear()
        self._key_message = self._check_status = ''
        self._checking = False
        self.preferencesChanged.emit()
        self._invalidate()
        if self._selection and self._config['automatic']:
            self._timer.start()

    @Slot(str)
    def saveKey(self, value):
        name = self._vault_name(self._config['provider'])
        value = value.strip()
        if len(value) > 2000 or any(c in value for c in '\r\n'):
            self._key_message = 'Некорректный API-ключ.'
        else:
            self._keys[name] = value
            try:
                self.vault.put(name, value)
                self._key_message = 'Ключ сохранён в системном хранилище.' if value else 'Ключ удалён.'
            except Exception:
                self._key_message = 'Системное хранилище недоступно. Ключ действует до закрытия Substance.'
            self._cache.clear()
            self._invalidate()
            if self._selection and self._config['automatic']:
                self._timer.start()
        self.preferencesChanged.emit()

    def _invalidate(self):
        self._serial += 1
        self._timer.stop()
        for job in self._jobs.values():
            job.cancelled.set()
        self._result = {}
        self._busy = False
        if self._checking:
            self._check_status = ''
        self._checking = False
        self.changed.emit()

    @Slot()
    def reset(self):
        self._selection = None
        self._invalidate()

    @Slot(str, int, int, str)
    def selectText(self, text, start, end, field):
        if self._closed:
            return
        selected = selected_plain_text(text, start, end)
        if not selected:
            if self._selection and self._selection['field'] == field:
                self.reset()
            return
        selection = {'text': selected, 'context': clean_text(text), 'field': field}
        if selection == self._selection:
            return
        self._invalidate()
        self._selection = selection
        self.changed.emit()
        if self._config['automatic']:
            self._timer.start()

    def _start(self, callback, receiver):
        serial = self._serial
        job = Work(serial, callback)
        # Use the QObject receiver, not a Python lambda executed on the worker.
        job.signals.result.connect(receiver)
        token = id(job)
        self._jobs[token] = job
        job.signals.done.connect(self._finished)
        self._pool.start(job)
        return job

    @Slot(int)
    def _finished(self, serial):
        # Work done signals are delivered after its result and keep the signal
        # owner alive until both queued signals have reached the GUI thread.
        for token, job in list(self._jobs.items()):
            if job.serial == serial:
                del self._jobs[token]

    @Slot()
    def lookup(self):
        if self._closed or not self._selection:
            return
        self._timer.stop()
        self._checking = False
        self._serial += 1
        serial = self._serial
        config, selection = dict(self._config), dict(self._selection)
        key = '' if config['localOnly'] else self._key()
        if selection['field'] == 'translation':
            config['source'] = 'auto'
        cache_key = json.dumps([selection, config], sort_keys=True)
        if cache_key in self._cache:
            self._result = deepcopy(self._cache[cache_key])
            self._busy = False
            self.changed.emit()
            return
        for job in self._jobs.values():
            job.cancelled.set()
        self._busy, self._result = True, {}
        self.changed.emit()

        def perform(job):
            text = selection['text']
            entries = lookup_dictionary(self.directory, text, config['source'], config['target']) if word_selection(text) else []
            result = {'text': text, 'kind': 'word' if word_selection(text) else 'phrase', 'entries': entries,
                      'translation': '', 'provider': '' if config['localOnly'] else PROVIDERS[config['provider']], 'error': '',
                      'dictionaryMissing': not any(self.directory.glob('*.sqlite')), 'complete': False}
            if config['localOnly']:
                result['complete'] = True
                return result
            if len(text) > 12000:
                raise AssistanceError('Выделите фрагмент длиной до 12 000 символов.')
            job.signals.result.emit(serial, deepcopy(result))
            if job.cancelled.is_set():
                return result
            try:
                translated, detected = translate([text], config['source'], config['target'], config, key,
                                                selection['context'] if config['context'] else '')
                result['translation'], result['detected'] = translated[0], detected
                if entries and config['translateDefinitions']:
                    # Only a short first page is translated automatically.
                    pending = [(sense, entry['definitionLanguage']) for entry in entries[:4]
                               for sense in entry['senses'][:4] if entry['definitionLanguage'] != config['target']]
                    for language in sorted({language for _, language in pending}):
                        if job.cancelled.is_set():
                            return result
                        senses = [sense for sense, lang in pending if lang == language]
                        while senses:
                            batch, size = [], 0
                            while senses and size + len(senses[0]['definition']) <= 10000:
                                sense = senses.pop(0)
                                batch.append(sense)
                                size += len(sense['definition'])
                            if job.cancelled.is_set():
                                return result
                            definitions, _ = translate([s['definition'] for s in batch], language, config['target'], config, key)
                            for sense, definition in zip(batch, definitions):
                                sense['translatedDefinition'] = definition
            except AssistanceError as exc:
                result['error'] = str(exc)
            result['complete'] = True
            return result

        self._active_cache_key = cache_key
        self._start(perform, self._received)

    @Slot(int, object)
    def _received(self, serial, result):
        if self._closed or serial != self._serial:
            return
        self._result = result
        self._busy = not result.get('complete', True)
        if not self._busy and not result.get('error'):
            self._cache[self._active_cache_key] = deepcopy(result)
            while len(self._cache) > 64:
                self._cache.popitem(last=False)
        self.changed.emit()

    @Slot()
    def checkConnection(self):
        if self._closed or self._checking or self._config['localOnly']:
            return
        self._invalidate()
        config, key = dict(self._config), self._key()
        self._checking, self._check_status = True, 'Проверка: перевод приветствия…'
        self.changed.emit()

        def check(job):
            if job.cancelled.is_set():
                return {}
            source = config['source'] if config['source'] != 'auto' else 'en'
            greeting = GREETINGS[source]
            result, _ = translate([greeting], source, config['target'], config, key)
            return {'message': 'Подключение работает: ' + greeting + ' → ' + result[0]}
        self._start(check, self._checked)

    @Slot(int, object)
    def _checked(self, serial, result):
        if not self._closed and serial == self._serial:
            self._checking = False
            self._check_status = result.get('error') or result.get('message', '')
            self.changed.emit()

    @Slot()
    def openSettings(self):
        self.settingsRequested.emit()

    @Slot()
    def copyTranslation(self):
        if self._result.get('translation'):
            QGuiApplication.clipboard().setText(self._result['translation'])

    @Property(str, constant=True)
    def libreCommand(self):
        return LIBRE_COMMAND

    @Slot()
    def copyLibreCommand(self):
        QGuiApplication.clipboard().setText(LIBRE_COMMAND)

    @Slot(str)
    def importDictionary(self, language):
        if self.installing or language not in dict(LANGUAGES):
            return
        path, _ = QFileDialog.getOpenFileName(None, 'Словарь Wiktextract / Kaikki', '', 'Словари (*.jsonl *.jsonl.gz *.ndjson *.ndjson.gz)')
        if path:
            self.installFile(path, language)

    def installFile(self, path, language):
        self._begin_install(path, language, 'import-' + language)

    @Slot(str)
    def downloadDictionary(self, pack):
        if pack in PACKS:
            self._begin_install(None, PACKS[pack]['language'], pack)

    def _begin_install(self, path, language, pack):
        if self._closed or self.installing or language not in dict(LANGUAGES):
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        self._install_status = 'Подготовка словаря…'

        def install(job):
            download = self.directory / (pack + '.download.jsonl.gz')
            try:
                source = path
                if source is None:
                    request = Request(PACKS[pack]['url'], headers={'User-Agent': 'Substance dictionary installer'})
                    with network_open(request, timeout=20) as response, download.open('wb') as output:
                        size = 0
                        while chunk := response.read(262144):
                            if job.cancelled.is_set():
                                raise AssistanceError('Установка словаря отменена.')
                            size += len(chunk)
                            if size > 1_000_000_000:
                                raise AssistanceError('Размер загрузки превышает 1 ГБ.')
                            output.write(chunk)
                            job.signals.progress.emit(f'Загружено {size / 1048576:.1f} МБ…')
                    source = download
                count = install_dictionary(source, self.directory / (pack + '.sqlite'), language, job.cancelled,
                                           lambda n: job.signals.progress.emit(f'Индексирование: {n:,} статей…'))
                return {'message': f'Словарь установлен: {count:,} статей.'}
            except (URLError, OSError, TimeoutError):
                raise AssistanceError('Не удалось установить словарь. Проверьте свободное место, сеть и доступность kaikki.org.') from None
            finally:
                download.unlink(missing_ok=True)
        job = Work(0, install)
        self._install = job
        job.signals.progress.connect(self._install_progress)
        job.signals.result.connect(self._installed)
        job.signals.done.connect(self._install_done)
        self._import_pool.start(job)
        self.changed.emit()

    @Slot(str)
    def _install_progress(self, message):
        if not self._closed:
            self._install_status = message
            self.changed.emit()

    @Slot(int, object)
    def _installed(self, serial, result):
        self._install_status = result.get('error') or result.get('message', '')
        self._cache.clear()

    @Slot(int)
    def _install_done(self, serial):
        self._install = None
        if not self._closed:
            self.changed.emit()
            if self._selection and self._config['automatic']:
                self.lookup()

    @Slot()
    def cancelInstall(self):
        if self._install:
            self._install.cancelled.set()
            self._install_status = 'Установка отменена. Прежняя база сохранена.'
            self.changed.emit()

    def shutdown(self):
        self._server.shutdown()
        self._closed = True
        self.reset()
        if self._install:
            self._install.cancelled.set()
        self._pool.clear()
        self._import_pool.clear()
        # HTTP calls have bounded timeouts and never touch GUI objects.
        self._pool.waitForDone(15000)
        self._import_pool.waitForDone(22000)
        self._keys.clear()
