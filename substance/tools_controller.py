"""Qt bridge for reviewable repairs, retiming and video cut markers."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot

from .document import atomic_write, plain_text
from .editor_tools import apply_plan, cue_info, lane_layout, plan
from .tool_jobs import AlignmentJob, SceneJob, video_identity
from .transcription import MODEL_BY_ID, whisper_executable
from .timecode import format_time
import json


class ToolsController(QObject):
    changed = Signal()
    lanesChanged = Signal()
    requested = Signal(str)
    analysisCompleted = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self._task = None
        self._snapshot = self._editor = None
        self._proposals = []
        self._kind = 'checks'
        self._status = ''
        self._progress = 0.
        self._result = None
        self._scenes = None
        self._media_context = None
        self._media_key = None
        self._display = backend.settings.value('audioDisplay', 'wave')
        self._snap_options = {name: backend.settings.value('snap/' + name, True, type=bool) for name in ('cuts', 'frames', 'cues')}
        self._lane_key, self._lanes = None, []
        self._drag_context = None
        self._preview_index = 0
        self._analysis_ready = False
        self._analysis_count = 0
        self._error = False
        self._options_stale = False
        backend.changed.connect(self._sync)
        backend.documentReplaced.connect(self._replaced)
        backend.media_controller.changed.connect(self._sync)
        backend.currentChanged.connect(self.changed)

    @Property(bool, notify=changed)
    def busy(self):
        return self._task is not None

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
    def displayMode(self):
        return self._display

    @Slot(str)
    def setDisplayMode(self, value):
        if value in ('wave', 'spectrum', 'tracks'):
            self._display = value
            self.backend.settings.setValue('audioDisplay', value)
            self.changed.emit()

    @Property('QVariantMap', notify=changed)
    def snapOptions(self):
        return dict(self._snap_options)

    @Slot(str, bool)
    def setSnapOption(self, key, value):
        if key in self._snap_options:
            self._snap_options[key] = value
            self.backend.settings.setValue('snap/' + key, value)
            self.changed.emit()

    @Property('QVariantList', notify=changed)
    def selectionIndices(self):
        return sorted(self.backend.selection)

    @Slot(int, int, result=int)
    def snapTime(self, value, distance):
        media = self.backend.media_controller
        candidates = []
        if self._snap_options['cuts']:
            candidates.extend(media.shot_changes)
        if self._snap_options['frames']:
            candidates.extend(media.keyframes)
        if self._snap_options['cues']:
            candidates.extend(edge for i, c in enumerate(self.backend.editor.document.cues)
                              if i not in self.backend.selection for edge in (c.start, c.end))
        closest = min(candidates, key=lambda t: abs(t - value), default=value)
        return closest if abs(closest - value) <= distance else value

    @Property('QVariantList', notify=lanesChanged)
    def lanes(self):
        key = id(self.backend.editor.document)
        if self._lane_key != key:
            self._lanes = lane_layout(self.backend.editor.document.cues)
            self._lane_key = key
        return self._lanes

    @Property('QVariantList', notify=changed)
    def rows(self):
        if self._snapshot is None:
            return []
        cues = {c.id: (i, c) for i, c in enumerate(self._snapshot.cues)}
        return [{'number': ', '.join(str(cues[c][0] + 1) for c in p.ids), 'reason': p.reason,
                 'before': '\n\n'.join(cue_info(cues[c][1]) for c in p.ids),
                 'after': '\n\n'.join(cue_info(c) for c in p.after) if p.after else 'Требуется ручная проверка',
                 'text': ' / '.join(plain_text(cues[c][1].output_text).replace('\n', ' ') for c in p.ids),
                 'review': p.review, 'checked': p.selected, 'applicable': p.applicable} for p in self._proposals]

    @Property(bool, notify=changed)
    def analysisReady(self):
        return self._analysis_ready

    @Property(int, notify=changed)
    def previewIndex(self):
        return self._preview_index

    @Property('QVariantMap', notify=changed)
    def summary(self):
        return {'analyzed': self._analysis_count, 'changes': sum(p.applicable for p in self._proposals),
                'review': sum(p.review for p in self._proposals),
                'unmatched': sum(not p.applicable for p in self._proposals),
                'selected': sum(p.selected and p.applicable for p in self._proposals)}

    @Property('QVariantList', notify=changed)
    def sceneRows(self):
        values = self._scenes['times'] if self._scenes else self.backend.media_controller.shot_changes
        return [{'time': when, 'label': format_time(when)} for when in values]

    @Property(bool, notify=changed)
    def canApply(self):
        return not self.busy and not self.stale and (self._scenes is not None or any(p.selected and p.applicable for p in self._proposals))

    @Property(bool, notify=changed)
    def stale(self):
        return self._snapshot is not None and (self._options_stale or self._editor is not self.backend.editor
            or self._snapshot != self.backend.editor.document
            or (self._kind in ('align', 'forced', 'retime', 'scenes') and self._media_context != self._context()))

    @Slot()
    def invalidate(self):
        if self._snapshot is not None:
            self._options_stale = True
            self.changed.emit()

    @Property('QVariantMap', notify=changed)
    def preview(self):
        if not self._snapshot or not 0 <= self._preview_index < len(self._proposals):
            return {'valid': False, 'start': 0, 'end': 1000, 'afterStart': 0, 'afterEnd': 1000, 'view': 0, 'span': 5000}
        p = self._proposals[self._preview_index]
        before = [c for c in self._snapshot.cues if c.id in p.ids]
        after = p.after or before
        def display(cue):
            text = plain_text(cue.output_text)
            duration = max(1, cue.end - cue.start)
            return {'text': text, 'start': cue.start, 'end': cue.end,
                    'startText': format_time(cue.start), 'endText': format_time(cue.end),
                    'duration': round(duration / 1000, 2),
                    'cps': round(len(text.replace('\n', '')) * 1000 / duration, 1)}
        start, end = min(c.start for c in before), max(c.end for c in before)
        astart, aend = min(c.start for c in after), max(c.end for c in after)
        view = max(0, min(start, astart) - 500)
        return {'valid': True, 'start': start, 'end': end, 'afterStart': astart, 'afterEnd': aend,
                'view': view, 'span': max(2000, max(end, aend) - view + 500),
                'text': '\n'.join(plain_text(c.output_text) for c in before), 'reason': p.reason,
                'applicable': p.applicable, 'checked': p.selected, 'review': p.review,
                'startText': format_time(start), 'endText': format_time(end),
                'afterStartText': format_time(astart), 'afterEndText': format_time(aend),
                'beforeCues': [display(c) for c in before], 'afterCues': [display(c) for c in p.after]}

    @Slot(int)
    def previewRow(self, index):
        self._preview_index = index
        self.changed.emit()

    @Slot(str)
    def open(self, kind):
        if self.busy:
            self.requested.emit(self._kind)
            return
        if self.backend.flush() and self.backend.flushCard():
            self._kind = kind
            self._snapshot = None
            self._proposals = []
            self._scenes = None
            self._status = ''
            self._error = False
            self._progress = 0.
            self._analysis_ready = False
            self._options_stale = False
            self.changed.emit()
            self.requested.emit(kind)

    @Slot(int, bool)
    def check(self, index, value):
        if 0 <= index < len(self._proposals) and self._proposals[index].applicable:
            self._proposals[index].selected = value
            self.changed.emit()

    @Slot(bool)
    def checkAll(self, value):
        for p in self._proposals:
            p.selected = value and p.applicable
        self.changed.emit()

    def _context(self):
        media = self.backend.media_controller
        try:
            stat = Path(media.path).stat() if media.path else None
            stamp = (stat.st_size, stat.st_mtime_ns) if stat else None
        except OSError:
            stamp = None
        return media.path, media.activeAudio, stamp

    @Property('QVariantMap', notify=changed)
    def timingPresets(self):
        defaults = {'Мягкая обработка': {'padding': True, 'lead': 80, 'tail': 120, 'bridge': True, 'bridgeGap': 80, 'bias': 100, 'protectOverlap': True},
                    'Только округление к кадрам': {'padding': False, 'bridge': False, 'snapCuts': False, 'frames': True, 'protectOverlap': True}}
        try:
            saved = json.loads(self.backend.settings.value('timing/processingPresets', '{}'))
            if isinstance(saved, dict):
                defaults.update({k: v for k, v in saved.items() if isinstance(v, dict)})
        except (ValueError, TypeError):
            pass
        return defaults

    @Slot(str, 'QVariantMap')
    def saveTimingPreset(self, name, values):
        name = name.strip()
        if not name or len(name) > 100:
            self._status = 'Введите название профиля до 100 символов.'
        else:
            values = dict(values)
            saved = dict(self.timingPresets)
            saved[name] = values
            self.backend.settings.setValue('timing/processingPresets', json.dumps(saved, ensure_ascii=False))
            self._status = 'Профиль обработки сохранён.'
        self.changed.emit()

    @Slot(str, 'QVariantMap')
    def analyze(self, kind, options):
        b = self.backend
        if self.busy or b.busy or not b.flush() or not b.flushCard():
            return
        options = dict(options)
        if kind == 'checks':
            if options.get('profile'):
                from .quality_profiles import validate_profile
                options.update(validate_profile(options['profile']))
            else:
                for name in ('readingSpeed', 'lineLength', 'lineCount', 'overlaps', 'lineCountLimit'):
                    options[name] = b.reviewSettings[name]
            options.setdefault('cps', b.cpsLimit)
            options.setdefault('width', b.lineLimit)
        try:
            self._kind = kind
            self._error = False
            self._editor = b.editor
            self._snapshot = deepcopy(b.editor.document)
            self._proposals, self._scenes, self._result = [], None, None
            self._preview_index = 0
            self._analysis_ready = False
            self._options_stale = False
            self._progress = 0.
            self._media_context = self._context()
            indices = sorted(b.selection) if options.get('selected', False) else list(range(b.count))
            if options.get('scope') == 'current':
                indices = [b.currentIndex] if b.currentIndex >= 0 else []
            self._analysis_count = len(indices)
            options = dict(options, cuts=list(b.media_controller.shot_changes))
            if kind != 'scenes' and not indices:
                raise ValueError('Нет реплик в выбранной области')
            if kind in ('checks', 'balance', 'split', 'merge'):
                self._proposals = plan(self._snapshot, indices, kind, options, b.mode == 'translation')
                self._status = f'Найдено предложений и замечаний: {len(self._proposals)}'
                self._analysis_ready = True
            elif kind == 'retime':
                from .timing_processing import process_timing
                if options.get('snapCuts') and not b.media_controller.shot_changes:
                    raise ValueError('Сначала найдите смены планов в меню «Медиа» или выключите привязку к склейкам.')
                self._proposals = process_timing(self._snapshot, indices, options,
                    cuts=b.media_controller.shot_changes, frame_times=b.frames.times)
                self._analysis_ready = True
                self._status = f'Предложений и замечаний: {len(self._proposals)}. Сравните время и прослушайте результат.'
            elif kind == 'forced':
                from .forced_alignment import MODEL_BY_ID as CTC_MODELS, ForcedAlignmentJob
                from .timecode import parse_time
                model = CTC_MODELS.get(options.get('model', 'ru'))
                if not model or b.alignment_models.busy:
                    raise ValueError('Дождитесь загрузки модели выравнивания.')
                if not b.media_controller.path:
                    raise ValueError('Откройте видео или аудио кнопкой «Подключить медиа».')
                start = parse_time(str(options.get('start', '00:00:00.000')))
                end = parse_time(str(options.get('end', '')))
                if not 0 <= start < end <= b.media_controller.duration:
                    raise ValueError('Укажите начало и конец диапазона внутри открытого медиа.')
                task = ForcedAlignmentJob(self._snapshot, indices, b.media_controller.path,
                    b.media_controller.activeAudio, model, b.alignment_models.directory/model.filename,
                    start, end, original=bool(options.get('original', True)))
                self._start(task)
            elif kind == 'scenes':
                if not b.media_controller.path or not b.media_controller.hasVideo:
                    raise ValueError('Откройте видео перед поиском смен планов')
                task = SceneJob(b.media_controller.path, max(1, min(100, int(options.get('threshold', 10)))),
                                b.media_controller.duration, b.data_dir / 'scene-cache')
                self._start(task)
            elif kind == 'align':
                if b.speech.busy:
                    raise ValueError('Дождитесь окончания распознавания или загрузки модели')
                if not b.media_controller.path:
                    raise ValueError('Откройте видео или аудио')
                model = MODEL_BY_ID.get(options.get('model', b.speech.savedModel))
                if not model or not whisper_executable():
                    raise ValueError('Движок Whisper отсутствует. Выполните scripts/build_whisper.py или обновите сборку.')
                model_path = b.speech.directory / model.filename
                if not model_path.is_file():
                    raise ValueError('Сначала скачайте выбранную модель кнопкой «Скачать модель»')
                shift = max(100, min(10000, int(options.get('maxShift', 1000))))
                options = dict(options, maxShift=shift)
                start = max(0, min(self._snapshot.cues[i].start for i in indices) - shift)
                end = max(self._snapshot.cues[i].end for i in indices) + shift
                if b.media_controller.duration:
                    end = min(end, b.media_controller.duration)
                if end <= start:
                    raise ValueError('Реплики находятся за пределами аудио')
                task = AlignmentJob(whisper_executable(), model, model_path, b.media_controller.path,
                                    b.media_controller.activeAudio, options.get('language', 'auto'), start, end, 42,
                                    cpu=bool(options.get('cpu', False)), document=self._snapshot,
                                    indices=indices, options=options)
                self._start(task)
            self.changed.emit()
            if self._analysis_ready:
                self.analysisCompleted.emit()
        except (ValueError, OSError, TypeError) as exc:
            self._error = True
            self._status = str(exc)
            self.changed.emit()

    def _start(self, task):
        self._task = task
        self._status = 'Подготовка анализа…'
        task.signals.progress.connect(self._update_progress)
        task.signals.result.connect(self._receive)
        task.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(task)

    def _receive(self, result):
        self._result = result

    def _update_progress(self, value, message):
        self._progress, self._status = value, message
        self.changed.emit()

    def _finished(self, result):
        self._task = None
        if result['error']:
            self._error = True
            self._status = result['error']
        elif result['cancelled']:
            self._status = 'Анализ остановлен; документ не изменён'
        elif self._editor is not self.backend.editor or self._media_context != self._context():
            self._error = True
            self._status = 'Документ или аудиодорожка изменились; повторите анализ'
        elif self._result is not None:
            if self._kind == 'scenes':
                self._scenes = self._result
                self._status = f'Найдено склеек: {len(self._scenes["times"])}. «Применить» заменит текущие маркеры.'
            else:
                self._proposals = self._result
                self._status = f'Проверено. Предложений и замечаний: {len(self._proposals)}'
            self._progress = 1.
            self._analysis_ready = True
        self._result = None
        self.changed.emit()
        if self._analysis_ready:
            self.analysisCompleted.emit()

    @Slot(result=bool)
    def apply(self):
        b = self.backend
        if self.busy or not b.flush() or not b.flushCard():
            return False
        try:
            if self._options_stale:
                raise ValueError('Настройки изменились. Повторите анализ перед применением.')
            if b.editor is not self._editor or (self._scenes is None and b.editor.document != self._snapshot):
                raise ValueError('Документ изменился после анализа. Повторите анализ.')
            current_id = b.current.get('id')
            selected_ids = {b.editor.document.cues[i].id for i in b.selection}
            if self._scenes is not None:
                if b.editor.document.media.get('shot_changes') != self._snapshot.media.get('shot_changes'):
                    raise ValueError('Маркеры изменились после анализа. Повторите анализ.')
                if self._context() != self._media_context or video_identity(b.media_controller.path) != self._scenes['identity']:
                    raise ValueError('Видео изменилось; повторите анализ')
                record = deepcopy(self._scenes)
                b.editor.transact('Маркеры смен планов', lambda d: d.media.update(shot_changes=record))
                self._save_markers(record)
            else:
                if self._kind in ('align', 'forced', 'retime') and self._context() != self._media_context:
                    raise ValueError('Аудиодорожка изменилась; повторите анализ')
                replacements = {old: [c.id for c in p.after] for p in self._proposals if p.selected and p.applicable for old in p.ids}
                apply_plan(b.editor, self._snapshot, self._proposals)
                selected_ids = {new for old in selected_ids for new in replacements.get(old, [old])}
                current_id = replacements.get(current_id, [current_id])[0]
            # Preserve identity-based selection across topology changes.
            b.selection = {i for i, c in enumerate(b.editor.document.cues) if c.id in selected_ids}
            b._current = next((i for i, c in enumerate(b.editor.document.cues) if c.id == current_id), min(b._current, b.count - 1))
            b._anchor = b._current
            if b._current >= 0 and not b.selection:
                b.selection = {b._current}
            b._refresh()
            self._proposals, self._scenes = [], None
            self._snapshot = None
            self._analysis_ready = False
            self._status = 'Изменения применены. Доступна общая отмена.'
            self._error = False
            if self._kind == 'align':
                b.notify('Тайминг обновлён. Изменения можно отменить.')
            self.changed.emit()
            return True
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._error = True
            self._status = str(exc)
            self.changed.emit()
            return False

    @Slot(int, bool)
    def play(self, index, after):
        if 0 <= index < len(self._proposals) and self._snapshot:
            p = self._proposals[index]
            cues = p.after if after else [c for c in self._snapshot.cues if c.id in p.ids]
            if cues and self._context() == self._media_context:
                self.backend.media_controller.playRange(min(c.start for c in cues), max(c.end for c in cues))

    @Slot(int)
    def locate(self, index):
        if 0 <= index < len(self._proposals):
            self._preview_index = index
            self.changed.emit()
            cue_id = self._proposals[index].ids[0]
            self.backend.selectCueId(cue_id)
            self.backend.seekCurrent()

    @Slot()
    def cancel(self):
        if self._task:
            self._task.cancel()
            self._status = 'Остановка анализа…'
            self.changed.emit()

    def _replaced(self):
        self.cancel()
        self._editor = None
        self._proposals, self._scenes = [], None
        self._snapshot = None
        self._analysis_ready = False
        self._lane_key = None
        self._media_key = None
        self.changed.emit()

    def _save_markers(self, record):
        path = self.backend.data_dir / 'scene-markers' / (record['identity'] + '.json')
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(record).encode())

    def _sync(self):
        lane_key = id(self.backend.editor.document)
        if lane_key != self._lane_key:
            self._lanes = lane_layout(self.backend.editor.document.cues)
            self._lane_key = lane_key
            self.lanesChanged.emit()
        media = self.backend.media_controller
        try:
            stat = Path(media.path).stat() if media.path else None
            key = (media.path, stat.st_size, stat.st_mtime_ns) if stat else None
            if key != self._media_key:
                self._media_key = key
                self._video_id = video_identity(media.path) if key else None
                self._cached_record = None
                if self._video_id:
                    path = self.backend.data_dir / 'scene-markers' / (self._video_id + '.json')
                    if path.is_file():
                        self._cached_record = json.loads(path.read_text('utf-8'))
            record = self.backend.editor.document.media.get('shot_changes', self._cached_record if key else None)
            values = record.get('times', []) if isinstance(record, dict) and record.get('identity') == getattr(self, '_video_id', None) else []
            values = sorted(set(v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0))
            if media.shot_changes != values:
                media.shot_changes = values
                media.analysisChanged.emit()
        except (OSError, ValueError, TypeError):
            if media.shot_changes:
                media.shot_changes = []
                media.analysisChanged.emit()
        self.changed.emit()

    @Slot(int)
    def toggleScene(self, position):
        b = self.backend
        if self.busy or not b.media_controller.path or not b.media_controller.hasVideo or not b.flush():
            return
        try:
            identity = video_identity(b.media_controller.path)
            values = list(b.media_controller.shot_changes)
            closest = min(values, key=lambda t: abs(t - position), default=None)
            if closest is not None and abs(closest - position) <= 80:
                values.remove(closest)
            else:
                values.append(max(0, position))
            record = {'identity': identity, 'times': sorted(set(values)), 'manual': True}
            if b._guard(lambda: b.editor.transact('Изменение маркера склейки', lambda d: d.media.update(shot_changes=record))):
                self._scenes = None
                self._save_markers(record)
        except OSError as exc:
            b.show_error(str(exc))

    @Slot(int)
    def seekScene(self, direction):
        media = self.backend.media_controller
        values = [t for t in media.shot_changes if (t - media.position) * direction > 1]
        if values:
            media.seek(min(values) if direction > 0 else max(values))

    @Slot('QVariantList', int)
    def moveCues(self, indices, delta):
        b = self.backend
        indices = sorted(set(int(i) for i in indices if 0 <= int(i) < b.count))
        if indices:
            delta = max(delta, -min(b.editor.document.cues[i].start for i in indices))
            def move():
                self._check_drag(indices)
                b.editor.shift(indices, delta)
            b._guard(move)
        self._drag_context = None

    @Slot()
    def beginTrackEdit(self):
        b = self.backend
        if b.flush():
            self._drag_context = (b.editor, [(c.id, c.start, c.end) for c in b.editor.document.cues])

    def _check_drag(self, indices):
        if self._drag_context:
            editor, cues = self._drag_context
            if editor is not self.backend.editor or any(i >= len(cues) or cues[i] != (editor.document.cues[i].id, editor.document.cues[i].start, editor.document.cues[i].end) for i in indices):
                raise ValueError('Реплики изменились во время перетаскивания. Повторите действие.')

    @Slot(int, int, int)
    def resizeCue(self, index, start, end):
        if 0 <= index < self.backend.count and 0 <= start < end:
            def resize():
                self._check_drag([index])
                self.backend.editor.update(index, start=start, end=end)
            self.backend._guard(resize)
        self._drag_context = None

    def shutdown(self):
        self.cancel()
