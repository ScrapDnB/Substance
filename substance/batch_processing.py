"""Preview a folder of subtitles; export immutable plans into a new run folder."""
from copy import deepcopy
from datetime import datetime
from pathlib import Path
import hashlib
import json

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .document import export_document, load_document, save_document, atomic_write
from .quality_profiles import findings, validate_profile, write_report
from .transcription import SpeechJob
from .workflow_controllers import SUBTITLE_FILTER


def fingerprint(path):
    paths = [Path(path)]
    if Path(path).suffix.lower() in ('.ass', '.ssa'):
        paths.append(Path(str(path) + '.substance'))
    result = []
    for item in paths:
        if not item.exists():
            result.append(None)
            continue
        digest = hashlib.sha256()
        with item.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        result.append(digest.hexdigest())
    return result


def replacement_pairs(text):
    result = []
    for i, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        if '→' not in line:
            raise ValueError(f'Замена в строке {i}: используйте вид «найти → заменить».')
        before, after = [part.strip() for part in line.split('→', 1)]
        if not before:
            raise ValueError(f'Замена в строке {i}: пустой искомый текст.')
        result.append((before, after))
    return result


def prepare_file(path, options):
    before = fingerprint(path)
    original = load_document(path)
    result = deepcopy(original)
    delta = int(options.get('shift', 0))
    replacements = replacement_pairs(options.get('replacements', ''))
    changed = 0
    for cue in result.cues:
        value = cue.output_text
        for source, target in replacements:
            value = value.replace(source, target)
        if value != cue.output_text:
            setattr(cue, 'translation' if cue.translation is not None else 'text', value)
            changed += 1
        cue.start += delta
        cue.end += delta
    result.validate()
    if fingerprint(path) != before:
        raise ValueError('Исходный файл изменился во время анализа. Повторите подготовку.')
    issues = findings(result, options['profile'])
    return {'source': str(path), 'fingerprint': before, 'document': result, 'original': original,
            'count': len(result.cues), 'changed': changed, 'issues': issues}


class BatchJob(SpeechJob):
    def __init__(self, paths, options, *, prepared=None, destination=''):
        super().__init__()
        self.paths, self.options, self.prepared, self.destination = paths, options, prepared, destination

    def execute(self):
        if self.prepared is None:
            results = []
            for i, path in enumerate(self.paths):
                self.check_cancelled()
                try:
                    result = prepare_file(path, self.options)
                    result.update(error='', checked=True)
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    result = {'source': path, 'error': str(exc), 'checked': False, 'count': 0, 'issues': []}
                results.append(result)
                self.signals.progress.emit((i+1) / len(self.paths), f'Проверено файлов: {i+1} / {len(self.paths)}')
            self.signals.result.emit({'prepared': results})
            return
        root = Path(self.destination)
        if not root.is_dir():
            raise ValueError('Выберите существующую папку для результата.')
        target = root / ('Substance-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
        serial = 2
        while True:
            try:
                target.mkdir()
                break
            except FileExistsError:
                target = root / ('Substance-' + datetime.now().strftime('%Y%m%d-%H%M%S') + f'-{serial}')
                serial += 1
        log, report, used = [], [], set()
        try:
            for i, item in enumerate(self.prepared):
                self.check_cancelled()
                entry = {'source': item['source'], 'result': '', 'error': ''}
                try:
                    if fingerprint(item['source']) != item['fingerprint']:
                        raise ValueError('Исходник изменился после предпросмотра; файл пропущен.')
                    source = Path(item['source'])
                    name = source.stem + '.' + self.options['format']
                    n = 2
                    while name.casefold() in used:
                        name = source.stem + f'-{n}.' + self.options['format']; n += 1
                    used.add(name.casefold())
                    output = target / name
                    if self.options['format'] == 'substance':
                        save_document(item['document'], output)
                    else:
                        export_document(item['document'], output)
                    entry['result'] = str(output)
                    report.extend(dict(r, reason=source.name + ': ' + r['reason']) for r in item['issues'])
                except (OSError, ValueError, TypeError) as exc:
                    entry['error'] = str(exc)
                log.append(entry)
                self.signals.progress.emit((i+1)/len(self.prepared), f'Записано файлов: {i+1} / {len(self.prepared)}')
        finally:
            # A stopped run has an honest durable record of already written files.
            atomic_write(target / 'Результаты.json', json.dumps({'files': log, 'stopped': self.cancelled.is_set()}, ensure_ascii=False, indent=2).encode())
            write_report(target / 'Проверка.html', report, 'Пакетная проверка')
            write_report(target / 'Проверка.csv', report)
            self.signals.result.emit({'destination': str(target), 'log': log})


class BatchController(QObject):
    changed = Signal()
    requested = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend, self._job, self._received = backend, None, None
        self._paths, self._prepared, self._options = [], [], {}
        self._status, self._destination, self._output = '', '', ''
        self._progress, self._stale = 0., True
        self._preview = 0

    @Property(bool, notify=changed)
    def busy(self):
        return self._job is not None

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property(str, notify=changed)
    def destination(self):
        return self._destination

    @Property(str, notify=changed)
    def output(self):
        return self._output

    @Property('QVariantList', notify=changed)
    def rows(self):
        if self._prepared:
            return [{'name': Path(p['source']).name, 'count': p['count'], 'checked': p['checked'],
                     'issues': len(p['issues']), 'error': p['error'], 'changed': p.get('changed', 0)} for p in self._prepared]
        return [{'name': Path(p).name, 'count': 0, 'checked': False, 'issues': 0, 'error': '', 'changed': 0} for p in self._paths]

    @Property('QVariantMap', notify=changed)
    def preview(self):
        if not 0 <= self._preview < len(self._prepared) or self._prepared[self._preview]['error']:
            return {}
        p = self._prepared[self._preview]
        from .timecode import format_time
        def lines(doc):
            return '\n\n'.join(f'{format_time(c.start)} → {format_time(c.end)}\n{c.output_text}' for c in doc.cues[:8])
        return {'before': lines(p['original']), 'after': lines(p['document']),
                'issues': '\n'.join(f'#{r["number"]}: {r["reason"]}' for r in p['issues'][:30])}

    @Property(bool, notify=changed)
    def canRun(self):
        return not self.busy and not self._stale and bool(self._destination) and any(p['checked'] and not p['error'] for p in self._prepared)

    @Slot()
    def open(self):
        self.requested.emit()

    @Slot()
    def chooseFiles(self):
        paths, _ = QFileDialog.getOpenFileNames(None, 'Субтитры для пакетной обработки', '', SUBTITLE_FILTER)
        if paths:
            self.setFiles(paths)

    @Slot('QVariantList')
    def setFiles(self, paths):
        if not self.busy:
            self._paths = list(dict.fromkeys(str(Path(p).resolve()) for p in paths))
            self._prepared, self._stale = [], True
            self._status = f'Выбрано файлов: {len(self._paths)}. Подготовьте результат.'
            self.changed.emit()

    @Slot()
    def chooseFolder(self):
        folder = QFileDialog.getExistingDirectory(None, 'Папка для результатов')
        if folder:
            self._destination = folder
            self.changed.emit()

    @Slot()
    def invalidate(self):
        self._stale = True
        self.changed.emit()

    @Slot(int)
    def previewRow(self, index):
        self._preview = index
        self.changed.emit()

    @Slot(int, bool)
    def check(self, index, value):
        if not self.busy and 0 <= index < len(self._prepared) and not self._prepared[index]['error']:
            self._prepared[index]['checked'] = value
            self.changed.emit()

    @Slot('QVariantMap')
    def analyze(self, options):
        if self.busy:
            return
        try:
            self._options = dict(options)
            self._options['profile'] = validate_profile(self.backend.quality_profiles.profile)
            if self._options.get('format') not in ('ass', 'srt', 'vtt', 'txt', 'substance'):
                raise ValueError('Выберите формат результата.')
            replacement_pairs(self._options.get('replacements', ''))
            if not self._paths:
                raise ValueError('Сначала выберите файлы.')
            self._prepared, self._stale, self._output = [], True, ''
            self._start(BatchJob(self._paths[:], self._options))
        except (ValueError, TypeError) as exc:
            self._status = str(exc)
            self.changed.emit()

    @Slot()
    def run(self):
        if self.canRun:
            self._start(BatchJob([], self._options, prepared=[p for p in self._prepared if p['checked'] and not p['error']], destination=self._destination))

    def _start(self, job):
        self._job, self._received = job, None
        self._progress, self._status = 0., 'Подготовка…'
        job.signals.result.connect(self._receive)
        job.signals.progress.connect(self._progressed)
        job.signals.finished.connect(self._finished)
        self.changed.emit()
        QThreadPool.globalInstance().start(job)

    def _receive(self, value):
        self._received = value

    def _progressed(self, value, message):
        self._progress, self._status = value, message
        self.changed.emit()

    def _finished(self, result):
        self._job = None
        received = self._received or {}
        if 'prepared' in received and not result['cancelled'] and not result['error']:
            self._prepared, self._stale = received['prepared'], False
            self._status = 'Результат подготовлен. Выберите файлы, проверьте примеры и укажите папку для записи.'
        if 'destination' in received:
            self._output = received['destination']
            good = sum(bool(r['result']) for r in received['log'])
            self._status = f'Сохранено файлов: {good}. Ошибок: {len(received["log"])-good}. Результаты: {self._output}'
            self._stale = True
        if result['cancelled']:
            self._status = 'Обработка остановлена. ' + ('Уже записанные файлы и отчёт: ' + self._output if self._output else 'Исходные файлы сохранены.')
        if result['error']:
            self._status = result['error']
        self.changed.emit()

    @Slot()
    def cancel(self):
        if self._job:
            self._job.cancel()

    @Slot()
    def reveal(self):
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if self._output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._output))

    def shutdown(self):
        self.cancel()
