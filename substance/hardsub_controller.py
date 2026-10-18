"""Reviewable hardsub imports with media/document guards and a single undo step."""
from copy import deepcopy
import math
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .document import Cue, plain_text
from .hardsub import HardsubJob, ass_text, engine_info, normalize
from .timecode import format_time, parse_time
from .tool_jobs import video_identity


class HardsubController(QObject):
    changed = Signal()
    requested = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self._job = None
        self._generation = 0
        self._info = {'engine': '', 'title': 'Проверка OCR…', 'languages': []}
        self._rows = []
        self._preview = ''
        self._preview_context = None
        self._status = ''
        self._progress = 0.
        self._error = False
        self._snapshot = self._editor = self._context = self._result = None
        self._identity = ''
        backend.documentReplaced.connect(self.reset)
        backend.changed.connect(self.changed)
        backend.media_controller.changed.connect(self.changed)
        backend.online.changed.connect(self.changed)

    @Property(bool, notify=changed)
    def busy(self):
        return self._job is not None

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(bool, notify=changed)
    def error(self):
        return self._error

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property(str, notify=changed)
    def engineTitle(self):
        return self._info['title']

    @Property(bool, notify=changed)
    def engineReady(self):
        return bool(self._info['engine'] and self._info['languages'])

    @Property('QStringList', notify=changed)
    def languages(self):
        return self._info['languages']

    @Property(str, notify=changed)
    def savedLanguage(self):
        saved = self.backend.settings.value('hardsub/language', '')
        return saved if saved in self.languages else next((l for l in self.languages if l in ('en-US', 'eng')), self.languages[0] if self.languages else '')

    @Property(str, notify=changed)
    def previewUrl(self):
        return self._preview if self._preview_context == self._media_context() else ''

    def _media_context(self):
        path = self.backend.media_controller.path
        try:
            stat = Path(path).stat()
            return path, stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def _current(self):
        b = self.backend
        return (self._snapshot is not None and b.editor is self._editor and
                b.editor.document == self._snapshot and self._context is not None and
                self._context == self._media_context())

    @Property(bool, notify=changed)
    def stale(self):
        return bool(self._rows) and not self._current()

    @Property(bool, notify=changed)
    def canAppend(self):
        return self.backend.speech.canAppend

    @Property(bool, notify=changed)
    def canApply(self):
        return not self.busy and not self.backend.busy and self.canAppend and self._current() and any(r['checked'] for r in self._rows)

    @Property('QVariantList', notify=changed)
    def rows(self):
        return [{**r, 'startLabel': format_time(r['start']), 'endLabel': format_time(r['end']),
                 'score': round(r['confidence'] * 100)} for r in self._rows]

    def _status_message(self, message, error=False):
        self._status, self._error = message, error
        self.changed.emit()

    @Slot()
    def refreshEngine(self):
        if self.busy:
            return
        try:
            self._info = engine_info(self.backend.settings.value('hardsub/executable', ''))
            self._status_message('OCR готов. Выберите область и запустите поиск.' if self.engineReady else
                'Установите Tesseract с языковыми пакетами и укажите его исполняемый файл. На macOS установите зависимости проекта с Apple Vision.')
        except (OSError, ValueError, RuntimeError) as exc:
            self._info = {'engine': '', 'title': 'OCR недоступен', 'languages': []}
            self._status_message(str(exc), True)

    @Slot()
    def chooseEngine(self):
        if self.busy:
            return
        path, _ = QFileDialog.getOpenFileName(None, 'Исполняемый файл Tesseract')
        if path:
            self.backend.settings.setValue('hardsub/executable', path)
            self.refreshEngine()

    @Slot()
    def automaticEngine(self):
        if not self.busy:
            self.backend.settings.remove('hardsub/executable')
            self.refreshEngine()

    @Slot()
    def open(self):
        if self.backend.flush() and self.backend.flushCard():
            if not self.busy:
                self.refreshEngine()
            self.requested.emit()

    @Slot('QVariantMap', result=bool)
    def analyze(self, options):
        b = self.backend
        if self.busy or b.busy or not b.flush() or not b.flushCard():
            return False
        try:
            if not b.media_controller.hasVideo or not self._media_context():
                raise ValueError('Сначала откройте видео')
            if not self.engineReady:
                raise ValueError('OCR недоступен. Проверьте движок и установленные языки.')
            start = parse_time(str(options.get('start', '00:00:00.000')))
            end = parse_time(str(options['end'])) if options.get('end') else b.media_controller.duration
            if not 0 <= start < end <= b.media_controller.duration:
                raise ValueError('Укажите диапазон в пределах видео')
            region = [float(options.get(k, default)) / 100 for k, default in
                      [('x', 0), ('y', 65), ('width', 100), ('height', 35)]]
            x, y, w, h = region
            if not all(math.isfinite(v) for v in region) or not (0 <= x < 1 and 0 <= y < 1 and .01 <= w <= 1 and .01 <= h <= 1 and x + w <= 1.000001 and y + h <= 1.000001):
                raise ValueError('Область должна находиться внутри кадра (координаты и размеры в процентах)')
            language = options.get('language', self.savedLanguage)
            if language not in self.languages:
                raise ValueError('Выбранный язык OCR не установлен')
            config = {'region': region, 'language': language, 'step': int(options.get('step', 250)),
                      'confidence': int(options.get('confidence', 60)), 'minimum': int(options.get('minimum', 300))}
            if not (100 <= config['step'] <= 2000 and 0 <= config['confidence'] <= 100 and 100 <= config['minimum'] <= 10000):
                raise ValueError('Проверьте шаг, уверенность и минимальное время текста')
            self._rows = []
            self._snapshot = deepcopy(b.editor.document)
            self._editor, self._context = b.editor, self._media_context()
            self._identity = ''
            b.settings.setValue('hardsub/language', language)
            self._launch(HardsubJob(b.media_controller.path, start, end, config, dict(self._info)))
            return True
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            self._status_message(str(exc), True)
            return False

    @Slot()
    def previewFrame(self):
        b = self.backend
        if self.busy or not b.media_controller.hasVideo or b.media_controller.duration <= 0:
            return
        self._launch(HardsubJob(b.media_controller.path, min(b.media_controller.position, max(0, b.media_controller.duration - 250)),
                               b.media_controller.duration, {'step': 250}, {}, preview=True))

    def _launch(self, job):
        self._job, self._result = job, None
        self._progress, self._error = 0., False
        token = self._generation
        context = self._media_context()
        job.signals.progress.connect(lambda value, status: self._on_progress(token, value, status))
        job.signals.result.connect(lambda result: self._receive(token, result))
        job.signals.finished.connect(lambda result: self._finished(token, context, job.preview, result))
        self._status = 'Получение кадра…' if job.preview else 'Поиск и распознавание текста в видео…'
        self.changed.emit()
        QThreadPool.globalInstance().start(job)

    def _on_progress(self, token, progress, status):
        if token == self._generation:
            self._progress, self._status = progress, status
            self.changed.emit()

    def _receive(self, token, result):
        if token == self._generation:
            self._result = result

    def _finished(self, token, context, preview, result):
        if token != self._generation:
            return
        self._job = None
        if result['cancelled']:
            self._status_message('Поиск остановлен. Документ не изменён.')
        elif result['error']:
            self._status_message(result['error'], True)
        elif context != self._media_context() or (not preview and not self._current()):
            self._status_message('Видео или документ изменились. Повторите поиск.', True)
        elif self._result is not None:
            if preview:
                self._preview = self._result['preview']
                self._preview_context = context
                self._status_message('Область выделена рамкой. Укажите координаты в процентах кадра.')
            else:
                self._rows = self._result['rows']
                self._identity = self._result['identity']
                self._progress = 1.
                self._status_message(f'Найдено текстовых фрагментов: {len(self._rows)}. Проверьте текст и таймкоды.' if self._rows else
                    'В выбранной области текст не найден. Проверьте язык, область и порог уверенности. Короткий текст мог попасть между проверенными кадрами.')
        self._result = None

    @Slot(int, bool)
    def check(self, index, checked):
        if not self.busy and 0 <= index < len(self._rows):
            self._rows[index]['checked'] = checked
            self.changed.emit()

    @Slot(bool)
    def checkAll(self, checked):
        if not self.busy:
            for row in self._rows:
                row['checked'] = checked
            self.changed.emit()

    @Slot(int, str)
    def editText(self, index, text):
        if not self.busy and 0 <= index < len(self._rows):
            self._rows[index]['text'] = text.strip()
            self._rows[index]['checked'] &= bool(text.strip())
            self.changed.emit()

    @Slot(int, str, str, str, result=bool)
    def editRow(self, index, text, start, end):
        if self.busy or not 0 <= index < len(self._rows):
            return False
        try:
            start, end = parse_time(start), parse_time(end)
            if not 0 <= start < end <= self.backend.media_controller.duration or not text.strip():
                raise ValueError('Проверьте текст и границы фрагмента: начало должно быть раньше конца и внутри видео.')
            self._rows[index].update(text=text.strip(), start=start, end=end)
            self.changed.emit()
            return True
        except (ValueError, TypeError) as exc:
            self._status_message(str(exc), True)
            return False

    @Slot(int)
    def seek(self, index):
        if self._context == self._media_context() and 0 <= index < len(self._rows):
            self.backend.media_controller.seek(self._rows[index]['start'])

    @Slot(bool, result=bool)
    def apply(self, for_translation):
        b = self.backend
        if self.busy or b.busy or not b.flush() or not b.flushCard():
            return False
        try:
            if not self.canAppend:
                raise ValueError('Оригинал этой онлайн-серии неизменяем. Импортируйте хардсаб в локальный документ.')
            if not self._current() or not self._identity or video_identity(b.media_controller.path) != self._identity:
                raise ValueError('Видео или документ изменились. Повторите поиск.')
            existing = [(c.start, c.end, normalize(plain_text(c.original or c.text))) for c in b.editor.document.cues if not c.comment]
            cues, skipped = [], 0
            for row in self._rows:
                if not row['checked'] or not row['text'].strip():
                    continue
                key = normalize(plain_text(ass_text(row['text'])))
                if any(a < row['end'] and row['start'] < z and text == key for a, z, text in existing):
                    skipped += 1
                    continue
                text = ass_text(row['text'])
                cue = Cue(start=row['start'], end=row['end'], text=text, original=text,
                          translation='' if for_translation else None,
                          extras={'authoring': True, 'hardsub': {'confidence': row['confidence']}})
                cues.append(cue)
                existing.append((cue.start, cue.end, key))
            if not cues:
                self._status_message(f'Нет новых реплик для добавления. Совпадений: {skipped}.')
                return False
            current_id = b.current.get('id')
            selected_ids = {b.editor.document.cues[i].id for i in b.selection}
            def append(document):
                for cue in cues:
                    document.register_source(cue)
                    document.cues.append(cue)
                document.cues.sort(key=lambda c: c.start)
            b.editor.transact('Добавить хардсаб', append)
            b._current = next((i for i, c in enumerate(b.editor.document.cues) if c.id == current_id), 0)
            b.selection = {i for i, c in enumerate(b.editor.document.cues) if c.id in selected_ids} or {b._current}
            if for_translation:
                b.setMode('translation')
            b._refresh()
            self._rows = []
            self._snapshot = None
            self._status_message(f'Добавлено реплик: {len(cues)}. Пропущено совпадений: {skipped}. Можно отменить одним действием.')
            return True
        except (OSError, ValueError, TypeError) as exc:
            self._status_message(str(exc), True)
            return False

    @Slot()
    def stop(self):
        if self._job:
            self._job.cancel()

    def reset(self):
        self.stop()
        self._generation += 1
        self._job = self._snapshot = self._result = None
        self._rows, self._preview = [], ''
        self.changed.emit()

    def shutdown(self):
        self.reset()
