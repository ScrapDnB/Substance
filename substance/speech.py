"""Main-thread orchestration of incremental subtitle authoring."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThreadPool, QTimer, Signal, Slot

from .document import Cue, Document, identity, plain_text
from .timecode import parse_time, format_time
from .transcription import LANGUAGES, MODELS, MODEL_BY_ID, ModelDownload, TranscriptionJob, whisper_executable
from .speech_timing import TimingOptions
from .speech_results import media_identity, mark_generated, matching_results, replacement_plan, replace_cues, intersects
import json


class SpeechController(QObject):
    changed = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.directory = backend.data_dir / 'speech-models'
        self._task = self._download = None
        self._editor = None
        self._session = ''
        self._originals = {}
        self._pending = []
        self._progress = 0.0
        self._status = 'Модель скачивается один раз. Распознавание работает на этом компьютере.'
        self._stopping = False
        self._error = False
        self._count = 0
        self._show_status = False
        self._source = None
        self._range = (0, 0)
        self._repeat = False
        self._buffered = []
        self._replaced = []
        self._known = {}
        self._prior_result = None
        self._preview_rows = []
        self._preview_media = None
        self._timer = QTimer(self, interval=120, singleShot=True)
        self._timer.timeout.connect(self._flush_segments)
        backend.documentReplaced.connect(self.detach)
        backend.online.changed.connect(self.changed)
        backend.media_controller.changed.connect(self.changed)

    @Property('QVariantList', notify=changed)
    def models(self):
        result = []
        for model in MODELS:
            path = self.directory / model.filename
            result.append({'id': model.id, 'title': model.title, 'bytes': model.size,
                           'installed': path.is_file() and path.stat().st_size == model.size,
                           'exists': path.is_file()})
        return result

    @Property('QStringList', constant=True)
    def modelTitles(self):
        return [model.title for model in MODELS]

    @Property('QVariantList', constant=True)
    def languages(self):
        return [{'id': code, 'title': title} for code, title in LANGUAGES]

    @Property(bool, notify=changed)
    def busy(self):
        return self._task is not None or self._download is not None

    @Property(bool, notify=changed)
    def running(self):
        return self._task is not None

    @Property(bool, notify=changed)
    def stopping(self):
        return self._stopping

    @Property(bool, notify=changed)
    def downloading(self):
        return self._download is not None

    @Property(bool, notify=changed)
    def engineReady(self):
        return bool(whisper_executable())

    @Property(bool, notify=changed)
    def canAppend(self):
        online = self.backend.online
        return not online.active or online.repository.snapshot.get('metadata', {}).get('authoring') is True

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(bool, notify=changed)
    def error(self):
        return self._error

    @Property(int, notify=changed)
    def addedCount(self):
        return self._count

    @Property('QVariantList', notify=changed)
    def previewRows(self):
        return [{'text': plain_text(row['text']), 'start': row['start'], 'end': row['end'],
                 'startText': format_time(row['start']), 'endText': format_time(row['end'])}
                for row in self._preview_rows]

    @Property(bool, notify=changed)
    def previewPlayable(self):
        media = self.backend.media_controller
        return bool(self._preview_media and self._preview_media[0] == media.path and media.hasMedia)

    @Property(bool, notify=changed)
    def replacing(self):
        return self._repeat and self.running

    @Slot(int)
    def playPreview(self, index):
        if self.previewPlayable and 0 <= index < len(self._preview_rows):
            row = self._preview_rows[index]
            media = self.backend.media_controller
            if media.activeAudio != self._preview_media[1]:
                media.setAudioTrack(self._preview_media[1])
            media.playRange(row['start'], row['end'])

    @Property(bool, notify=changed)
    def statusVisible(self):
        return self.busy or self._show_status

    @Slot()
    def dismiss(self):
        if not self.busy:
            self._show_status = False
            self.changed.emit()

    @Property(bool, notify=changed)
    def canDiscard(self):
        return bool(self._originals) and self._editor is self.backend.editor and not self.running

    @Property(str, constant=True)
    def savedModel(self):
        return self.backend.settings.value('speechModel', 'small')

    @Property(str, constant=True)
    def savedLanguage(self):
        return self.backend.settings.value('speechLanguage', 'auto')

    @Property('QVariantMap', notify=changed)
    def timing(self):
        try:
            return TimingOptions.from_dict(json.loads(self.backend.settings.value('speechTiming', '{}'))).to_dict()
        except (ValueError, TypeError):
            return TimingOptions().to_dict()

    def _set_status(self, text, error=False):
        self._status, self._error = text, error
        self._show_status = True
        self.changed.emit()

    @Slot(str)
    def download(self, model_id):
        if self.busy or model_id not in MODEL_BY_ID:
            return
        self._progress = 0
        job = self._download = ModelDownload(MODEL_BY_ID[model_id], self.directory)
        job.signals.progress.connect(self._update_progress)
        job.signals.finished.connect(self._download_finished)
        self._set_status('Подключение к серверу моделей…')
        QThreadPool.globalInstance().start(job)

    @Slot(object)
    def _download_finished(self, result):
        self._download = None
        self._progress = 0 if result['cancelled'] or result['error'] else 1
        self._stopping = False
        self._set_status(result['error'] or ('Скачивание остановлено' if result['cancelled'] else 'Модель скачана и проверена. Можно начать распознавание.'), bool(result['error']))

    @Slot(str)
    def removeModel(self, model_id):
        if self.busy or model_id not in MODEL_BY_ID:
            return
        try:
            (self.directory / MODEL_BY_ID[model_id].filename).unlink(missing_ok=True)
            self._set_status('Модель удалена с компьютера')
        except OSError as exc:
            self._set_status(str(exc), True)

    @Slot(float, str)
    def _update_progress(self, value, status):
        sender = self.sender()
        if sender is not None and not any(job and sender is job.signals for job in (self._task, self._download)):
            return
        if self._stopping:
            return
        self._progress = max(self._progress, value)
        if self._repeat and self.running:
            status += ' Прежний результат остаётся до завершения.'
        self._set_status(status)

    @Slot('QVariantMap', result=bool)
    def start(self, options):
        if self.busy or self.backend.busy:
            return False
        try:
            model = MODEL_BY_ID[options.get('model', '')]
            language = options.get('language', 'auto')
            if language not in dict(LANGUAGES):
                raise ValueError('Выберите язык распознавания')
            executable = whisper_executable()
            if not executable:
                raise ValueError('Движок распознавания отсутствует. Для запуска из исходников выполните scripts/build_whisper.py.')
            path = self.directory / model.filename
            if not path.is_file() or path.stat().st_size != model.size:
                raise ValueError('Сначала скачайте выбранную модель')
            media = self.backend.media_controller
            if not media.path or not Path(media.path).is_file() or media.duration <= 0:
                raise ValueError('Подключите видео или аудио и дождитесь загрузки')
            track = int(options.get('track', 0))
            if not 0 <= track < max(1, len(media.audioTracks)):
                raise ValueError('Выберите аудиодорожку')
            start = parse_time(options.get('start', '00:00:00.000'))
            end = parse_time(options['end']) if options.get('end') else media.duration
            width = int(options.get('width', 42))
            timing = TimingOptions.from_dict(options.get('timing', self.timing))
            if start < 0 or end <= start or end > media.duration or not 20 <= width <= 100:
                raise ValueError('Проверьте диапазон времени и длину строки (20–100 символов)')
            new_document = bool(options.get('newDocument', False))
            if not new_document and not self.canAppend:
                raise ValueError('Оригинал онлайн-серии неизменяем. Выберите новый локальный документ.')
            if not self.backend.flushCard() or not self.backend.flush():
                return False
            media_path = media.path
            if new_document:
                if not self.backend._confirm_unsaved():
                    return False
                document = Document(media=deepcopy(self.backend.editor.document.media), fps=self.backend.editor.document.fps)
                document.media['path'] = media_path
                self.backend._set_document(document, '')
            self._editor = self.backend.editor
            self._known = dict(self._originals)
            self._prior_result = (self._session, dict(self._originals), list(self._replaced))
            self._source = media_identity(media_path, track)
            self._range = (start, end)
            self._repeat = bool(matching_results(self._editor.document, self._source, start, end, known=self._known))
            self._buffered, self._replaced = [], []
            self._preview_rows = []
            self._preview_media = (media_path, track)
            self._session = identity('speech')
            self._originals, self._pending = {}, []
            self._count, self._progress, self._stopping = 0, 0, False
            job = self._task = TranscriptionJob(executable, model, path, media_path, track, language,
                                                start, end, width, bool(options.get('cpu', False)), timing)
            job.signals.segment.connect(self._receive_segment)
            job.signals.progress.connect(self._update_progress)
            job.signals.finished.connect(self._finished)
            self.backend.settings.setValue('speechModel', model.id)
            self.backend.settings.setValue('speechLanguage', language)
            self.backend.settings.setValue('speechTiming', json.dumps(timing.to_dict()))
            self._set_status('Повторное распознавание: прежние реплики сохранятся до завершения.' if self._repeat else 'Подготовка распознавания…')
            QThreadPool.globalInstance().start(job)
            return True
        except (KeyError, ValueError, TypeError, OSError) as exc:
            self._set_status(str(exc), True)
            return False

    @Slot(object)
    def _receive_segment(self, segment):
        if self.sender() is not None and (not self._task or self.sender() is not self._task.signals):
            return
        if self._editor is not self.backend.editor:
            self.stop()
            return
        self._pending.append(segment)
        if not self._timer.isActive():
            self._timer.start()

    @Slot()
    def _flush_segments(self):
        self._timer.stop()
        if not self._pending or self._editor is not self.backend.editor:
            self._pending.clear()
            return
        segments, self._pending = self._pending, []
        self._preview_rows.extend(deepcopy(segments))
        if self._repeat:
            self._buffered.extend(segments)
            self._count += len(segments)
            self.changed.emit()
            return
        cues = [Cue(start=row['start'], end=row['end'], text=row['text'], original=row['text'],
                    extras={'authoring': True, 'transcription_session': self._session}) for row in segments]
        editor = self._editor
        previous_count = len(editor.document.cues)
        try:
            def append(document):
                for cue in cues:
                    mark_generated(document, cue, self._source)
                    document.cues.append(cue)
            # Coalesce adjacent machine batches, never across a manual edit,
            # save boundary, undo, or redo. History remains in chronological order.
            label = 'Распознавание речи ' + self._session
            merge = bool(editor.undo_stack and editor.undo_stack[-1].label == label
                         and not editor.redo_stack and editor.revision != editor.saved_revision)
            editor.transact(label, append)
            if merge and len(editor.undo_stack) >= 2 and editor.undo_stack[-2].label == label:
                current, previous = editor.undo_stack.pop(), editor.undo_stack.pop()
                current.before, current.before_revision = previous.before, previous.before_revision
                editor.undo_stack.append(current)
            self._originals.update({cue.id: deepcopy(cue) for cue in cues})
            self._count += len(cues)
            backend = self.backend
            backend.model.rebuild(incremental=True)
            backend.changed.emit()
            backend._preview_timer.start()
            if previous_count == 0 and backend._current == -1:
                backend._current = 0
                backend.selection = {0}
                backend.model.update_selection()
                backend.currentChanged.emit()
            if not backend.online.checkpoint():
                raise ValueError(backend.online.status)
            self.changed.emit()
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self._set_status(str(exc), True)
            self.stop()

    def _apply_repeat(self):
        backend, editor = self.backend, self._editor
        if not self._buffered or editor is not backend.editor:
            return False
        if not backend.flushCard() or not backend.flush():
            self._set_status('Не удалось применить повторное распознавание: проверьте текущую правку. Прежние реплики сохранены.', True)
            return False
        reviewed = [row['cue_id'] for row in backend.online.reviews.entries if row['state'] == 'open'] if backend.online.active else []
        removed, protected = replacement_plan(editor.document, self._source, *self._range,
                                               known=self._known, reviewed=reviewed)
        # A coarser new phrase can span both a protected manual edit and an
        # untouched old cue. Skipping that phrase must preserve both old rows.
        old_bounds = {cue.id: (cue.start, cue.end) for cue in editor.document.cues if cue.id in removed}
        while True:
            blocked = [row for row in self._buffered if any(intersects((row['start'], row['end']), bound) for bound in protected)]
            keep = {cid for cid in removed if any(intersects(old_bounds[cid], (row['start'], row['end'])) for row in blocked)}
            if not keep:
                break
            removed -= keep
            protected.extend(old_bounds[cid] for cid in keep)
        rows = [row for row in self._buffered if not any(intersects((row['start'], row['end']), bound) for bound in protected)]
        self._buffered.clear()
        if not rows:
            self._count = 0
            self._set_status('Прежние реплики сохранены: результат пересекается с ручными правками или репликами без сведений о происхождении.')
            return False
        cues = [Cue(start=row['start'], end=row['end'], text=row['text'], original=row['text'],
                    extras={'authoring': True, 'transcription_session': self._session}) for row in rows]
        current = editor.document.cues[backend._current] if 0 <= backend._current < backend.count else None
        selected = {editor.document.cues[i].id for i in backend.selection}
        replaced = [deepcopy(cue) for cue in editor.document.cues if cue.id in removed]
        def apply(document):
            for cue in cues:
                mark_generated(document, cue, self._source)
            replace_cues(document, removed, cues)
        try:
            editor.transact('Повторное распознавание речи', apply)
            self._replaced = replaced
            self._originals = {cue.id: deepcopy(cue) for cue in cues}
            self._count = len(cues)
            indices = {cue.id: i for i, cue in enumerate(editor.document.cues)}
            preserved_current = current is not None and current.id in indices
            backend._current = indices[current.id] if preserved_current else indices[min(cues, key=lambda cue: abs(cue.start - (current.start if current else 0))).id]
            backend.selection = {indices[cid] for cid in selected if cid in indices} or {backend._current}
            backend._refresh(current=not preserved_current)
            return True
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self._set_status(str(exc) + ' Прежние реплики сохранены.', True)
            return False

    @Slot(object)
    def _finished(self, result):
        if self.sender() is not None and (not self._task or self.sender() is not self._task.signals):
            return
        self._flush_segments()
        repeated = self._repeat
        if repeated and not result['error'] and not result['cancelled'] and not self._error:
            applied = self._apply_repeat()
        else:
            applied = False
        self._task = None
        self._stopping = False
        if repeated:
            self._buffered.clear()
            if not applied and self._prior_result is not None:
                self._session, self._originals, self._replaced = self._prior_result
            if self._error:
                self.changed.emit()
            elif result['error']:
                self._set_status(result['error'] + ' Прежний результат сохранён.', True)
            elif result['cancelled']:
                self._set_status('Повторное распознавание остановлено. Прежний результат сохранён.')
            elif applied:
                self._progress = 1
                self._set_status(f'Результат обновлён. Реплик: {self._count}. Ручные правки сохранены.')
            elif self._count == 0 and not self._error:
                self._set_status('Речь не обнаружена или новые реплики защищены ручными правками. Прежний результат сохранён.')
            else:
                self.changed.emit()
            return
        if self._error:
            self.changed.emit()
            return
        if result['error']:
            self._set_status(result['error'] + f' Готовые реплики сохранены: {self._count}.', True)
        elif result['cancelled']:
            self._set_status(f'Остановлено. Готовые реплики сохранены: {self._count}.')
        else:
            self._progress = 1
            self._set_status(f'Распознавание завершено. Добавлено реплик: {self._count}.' if self._count else 'Распознавание завершено. Речь не обнаружена.')

    @Slot()
    def stop(self):
        job = self._task or self._download
        if job:
            job.cancel()
            self._stopping = True
            if not self._error:
                self._set_status('Остановка… Готовые реплики останутся в документе.')
            else:
                self.changed.emit()

    @Slot()
    def discard(self):
        if not self.canDiscard or not self.backend.flushCard() or not self.backend.flush():
            return
        editor = self._editor
        removed = {cue.id for cue in editor.document.cues if cue.id in self._originals and cue == self._originals[cue.id]}
        retained = [cue.id for cue in editor.document.cues if cue.id in self._originals and cue.id not in removed]
        # A split/merge may still refer to the original source. Preserve both
        # fragments when any descendant was edited manually.
        edited_sources = {sid for cue in editor.document.cues if cue.id not in removed for sid in cue.source_ids}
        reviewed = {cue_id for review in editor.document.reviews for cue_id in review.cue_ids}
        removed -= reviewed
        removed = {cue_id for cue_id in removed if not edited_sources.intersection(self._originals[cue_id].source_ids)}
        current_id = editor.document.cues[self.backend._current].id if 0 <= self.backend._current < self.backend.count else ''
        selection_ids = {editor.document.cues[i].id for i in self.backend.selection}
        def remove(document):
            document.cues = [cue for cue in document.cues if cue.id not in removed]
            # Restore the old result when discarding a successful repeat run.
            # Keep edited new cues and do not restore old rows over them.
            origins = {sid: (cue.start, cue.end) for cue in self._originals.values() for sid in cue.source_ids}
            protected = [bound for cue in document.cues if set(cue.source_ids).intersection(origins)
                         for bound in [(cue.start, cue.end)] + [origins[sid] for sid in cue.source_ids if sid in origins]]
            existing = {cue.id for cue in document.cues}
            restored = [deepcopy(cue) for cue in self._replaced if cue.id not in existing
                        and not any(intersects((cue.start, cue.end), bound) for bound in protected)]
            for cue in restored:
                index = next((i for i, row in enumerate(document.cues) if row.start > cue.start), len(document.cues))
                document.cues.insert(index, cue)
        if self.backend._guard(lambda: editor.transact('Отмена распознавания', remove), current=False):
            indices = {cue.id: i for i, cue in enumerate(editor.document.cues)}
            self.backend._current = indices.get(current_id, min(self.backend._current, self.backend.count - 1))
            self.backend.selection = {indices[cue_id] for cue_id in selection_ids if cue_id in indices}
            self.backend.model.update_selection()
            self.backend.currentChanged.emit()
            self._originals.clear()
            self._replaced.clear()
            self._preview_rows.clear()
            self._set_status(f'Удалено машинных реплик: {len(removed)}. Ручные правки сохранены: {len(retained)}.')

    def detach(self):
        if self._task:
            job, self._task = self._task, None
            job.cancel()
            # Queued emissions from an old document must never reach a new one.
            for signal in (job.signals.segment, job.signals.progress, job.signals.finished):
                signal.disconnect()
        self._timer.stop()
        self._pending.clear()
        self._originals.clear()
        self._buffered.clear()
        self._replaced.clear()
        self._known.clear()
        self._preview_rows.clear()
        self._preview_media = None
        self._prior_result = None
        self._editor = None
        self._stopping = False
        if not self._download:
            self._status = 'Модель скачивается один раз. Распознавание работает на этом компьютере.'
            self._error = False
            self._show_status = False
        self.changed.emit()

    def shutdown(self):
        self.detach()
        if self._download:
            self._download.cancel()
