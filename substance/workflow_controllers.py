"""Desktop bridges for file comparison, field transfer and delivery profiles."""
from copy import deepcopy
from pathlib import Path
import json
import html

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .document import Document, load_document, parse_ass, parse_srt, parse_txt, plain_text
from .quality_profiles import DEFAULT_PROFILE, findings, validate_profile, write_report
from .timecode import format_time
from .transfer import Pair, differences, pair_lines, transfer, word_highlights

SUBTITLE_FILTER = 'Субтитры и проекты (*.ass *.ssa *.srt *.vtt *.txt *.substance)'
DIFFERENCE_FILTERS = [('all', 'Все типы'), ('text', 'Текст'), ('time', 'Время'),
                      ('character', 'Персонаж'), ('format', 'Стиль, слой и отступы'),
                      ('added', 'Добавленные реплики'), ('removed', 'Удалённые реплики')]
DIFFERENCE_FIELDS = {'text': 'Текст', 'time': 'Время', 'character': 'Персонаж', 'format': 'Оформление'}


class TransferController(QObject):
    changed = Signal()
    previewChanged = Signal()
    requested = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self._snapshot = self._editor = self._reference = None
        self._pairs = []
        self._fields = ['text', 'time']
        self._structure, self._differences_only = False, True
        self._difference_filter = 'all'
        self._status, self._name, self._kind = '', '', 'compare'
        self._index = -1
        self.changed.connect(self.previewChanged)
        backend.changed.connect(self.changed)
        backend.documentReplaced.connect(self.reset)

    @Property(str, notify=changed)
    def kind(self):
        return self._kind

    @Property(str, notify=changed)
    def referenceName(self):
        return self._name

    @Property(str, notify=changed)
    def status(self):
        return ('Документ изменился. Обновите сравнение перед применением.' if self.stale else self._status)

    @Property(bool, notify=changed)
    def stale(self):
        return self._snapshot is not None and (self.backend.editor is not self._editor or
            self.backend.editor.document != self._snapshot or bool(self.backend.draft))

    def _view_pairs(self):
        if not self._snapshot or not self._reference:
            return []
        visible = []
        for i, pair in enumerate(self._pairs):
            if self._kind == 'paste' and pair.reference is None:
                continue
            differences = self._diff(pair)
            if self._differences_only and not differences:
                continue
            kind = self._difference_filter
            matches = (kind == 'all' or kind == 'added' and pair.current is None
                       or kind == 'removed' and pair.reference is None
                       or DIFFERENCE_FIELDS.get(kind) in differences)
            if matches:
                visible.append((i, pair))
        return visible

    @Property('QVariantList', constant=True)
    def differenceFilters(self):
        return [{'id': key, 'title': title} for key, title in DIFFERENCE_FILTERS]

    @Property(str, notify=changed)
    def differenceFilter(self):
        return self._difference_filter

    @Property(bool, notify=changed)
    def differencesOnly(self):
        return self._differences_only

    @Slot(str)
    def setDifferenceFilter(self, value):
        if value not in {key for key, _ in DIFFERENCE_FILTERS}:
            return
        self._difference_filter = value
        if value != 'all':
            self._differences_only = True
        self._ensure_preview()
        self.changed.emit()

    def _diff(self, p):
        return differences(self._snapshot.cues[p.current] if p.current is not None else None,
                           self._reference.cues[p.reference] if p.reference is not None else None)

    def _cue(self, cue, number):
        if cue is None:
            return {'number': '—', 'text': 'Реплики нет', 'html': 'Реплики нет', 'time': '', 'character': '', 'style': ''}
        return {'number': str(number + 1), 'text': plain_text(cue.output_text), 'rawText': cue.output_text,
                'html': html.escape(plain_text(cue.output_text)).replace('\n','<br>'),
                'time': format_time(cue.start) + ' → ' + format_time(cue.end), 'character': cue.character,
                'style': cue.ass_fields.get('Style', 'Default')}

    @Property('QVariantList', notify=changed)
    def rows(self):
        return [{'key': i, 'left': p.current + 1 if p.current is not None else 0,
                 'right': p.reference + 1 if p.reference is not None else 0,
                 'text': plain_text((self._snapshot.cues[p.current] if p.current is not None else self._reference.cues[p.reference]).output_text),
                 'reason': ', '.join(self._diff(p)) or 'Совпадают', 'checked': p.chosen}
                for i, p in self._view_pairs()]

    @Property(int, notify=previewChanged)
    def previewIndex(self):
        return next((row for row, (key, _) in enumerate(self._view_pairs()) if key == self._index), -1)

    def _ensure_preview(self):
        visible = self._view_pairs()
        if not any(key == self._index for key, _ in visible):
            self._index = visible[0][0] if visible else -1

    @Property('QVariantMap', notify=previewChanged)
    def preview(self):
        if not self._snapshot or not self._reference or not 0 <= self._index < len(self._pairs):
            return {}
        p = self._pairs[self._index]
        left = self._snapshot.cues[p.current] if p.current is not None else None
        right = self._reference.cues[p.reference] if p.reference is not None else None
        after = deepcopy(left)
        if after is not None and right is not None:
            if 'text' in self._fields:
                if after.translation is not None or self.backend.mode == 'translation':
                    after.translation = right.output_text
                else:
                    after.text = right.output_text
            if 'time' in self._fields:
                after.start, after.end = right.start, right.end
            if 'character' in self._fields:
                after.character = right.character
        if left is None and self._structure:
            after = right
        if right is None and self._structure:
            after = None
        current_view, reference_view = self._cue(left,p.current), self._cue(right,p.reference)
        if left is not None and right is not None:
            current_view['html'], reference_view['html'] = word_highlights(left.output_text,right.output_text)
        return {'left': current_view, 'right': reference_view,
                'after': self._cue(after, p.current if p.current is not None else p.reference),
                'reason': ', '.join(self._diff(p)) or 'Совпадают', 'checked': p.chosen}

    @Property(int, notify=changed)
    def chosenCount(self):
        fields = {'text': 'Текст', 'time': 'Время', 'character': 'Персонаж', 'format': 'Оформление'}
        return sum(bool(p.chosen and (self._structure if p.current is None or p.reference is None
                   else any(fields[f] in self._diff(p) for f in self._fields))) for p in self._pairs)

    @Property(bool, notify=changed)
    def canApply(self):
        return bool(self._reference and self.chosenCount and (self._fields or self._structure) and not self.stale and not self.backend.busy)

    @Slot()
    def reset(self):
        self._snapshot = self._reference = self._editor = None
        self._pairs = []
        self._index = -1
        self._difference_filter, self._differences_only = 'all', True
        self._name = self._status = ''
        self.changed.emit()

    @Slot(str)
    def open(self, kind):
        b = self.backend
        if b.busy or not b.flush() or not b.flushCard():
            return
        self.reset()
        self._kind = kind
        self._fields = ['text'] if kind == 'paste' else ['text', 'time']
        self._structure = False
        self._snapshot, self._editor = deepcopy(b.editor.document), b.editor
        self.changed.emit()
        self.requested.emit()
        if kind == 'paste':
            self.loadClipboard()

    @Slot()
    def chooseReference(self):
        path, _ = QFileDialog.getOpenFileName(None, 'Файл, из которого взять данные', '', SUBTITLE_FILTER)
        if path:
            self.loadReference(path)

    @Slot(str, result=bool)
    def loadReference(self, path):
        try:
            reference = load_document(path)
            reference.validate()
            self._load(reference, Path(path).name)
            return True
        except (ValueError, OSError, TypeError, KeyError) as exc:
            self._status = str(exc)
            self.changed.emit()
            return False

    def _load(self, reference, name):
        self._reference, self._name = reference, name
        self.refresh()

    @Slot()
    def loadClipboard(self):
        from PySide6.QtGui import QGuiApplication
        try:
            mime = QGuiApplication.clipboard().mimeData()
            if mime is None:
                raise ValueError('Буфер обмена пуст. Скопируйте реплики или выберите файл.')
            if mime.hasFormat('application/x-substance-cues'):
                reference = Document.from_dict(json.loads(bytes(mime.data('application/x-substance-cues'))))
            else:
                text = mime.text()
                if not text.strip():
                    raise ValueError('Буфер обмена пуст. Скопируйте реплики или выберите файл.')
                reference = parse_ass('[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n' + text) if text.startswith(('Dialogue:', 'Comment:')) else parse_srt(text) if ' --> ' in text else parse_txt(text)
            reference.validate()
            self._load(reference, 'Буфер обмена')
        except (ValueError, TypeError, KeyError) as exc:
            self._status = str(exc)
            self.changed.emit()

    @Slot()
    def refresh(self):
        if not self._reference or not self.backend.flush() or not self.backend.flushCard():
            return
        self._snapshot, self._editor = deepcopy(self.backend.editor.document), self.backend.editor
        if self._kind == 'paste':
            selected = sorted(self.backend.selection)
            if not selected:
                self._pairs = []
                self._status = 'Выделите реплики, поверх которых нужно вставить данные, и обновите сравнение.'
            else:
                selection = {index: j for j, index in enumerate(selected)}
                self._pairs = [Pair(i, selection[i] if selection.get(i, len(self._reference.cues)) < len(self._reference.cues) else None,
                                    i in selection and selection[i] < len(self._reference.cues)) for i in range(self.backend.count)]
                self._status = f'В буфере/файле: {len(self._reference.cues)}. Выделено: {len(selected)}. Перенос по порядку; проверьте соответствие.'
                if len(self._reference.cues) != len(selected):
                    self._status += ' Количество различается: лишние строки не вставляются.'
        else:
            self._pairs = pair_lines(self._snapshot.cues, self._reference.cues)
            self._status = 'Проверьте пары реплик и отметьте изменения. До применения документ не меняется.'
        self._index = next((i for i, p in enumerate(self._pairs) if self._diff(p)), 0)
        self._ensure_preview()
        self.changed.emit()

    @Slot(str, bool)
    def setField(self, name, enabled):
        if name in ('text', 'time', 'character', 'format'):
            self._fields = [k for k in self._fields if k != name] + ([name] if enabled else [])
        elif name == 'structure':
            self._structure = enabled
        elif name == 'differences':
            self._differences_only = enabled
            if not enabled:
                self._difference_filter = 'all'
            self._ensure_preview()
        self.changed.emit()

    @Slot(int)
    def previewRow(self, index):
        if any(key == index for key, _ in self._view_pairs()) and index != self._index:
            self._index = index
            self.previewChanged.emit()

    @Slot(int)
    def navigate(self, direction):
        visible = self._view_pairs()
        if not visible or not direction:
            return
        row = self.previewIndex
        target = 0 if row < 0 else max(0, min(len(visible)-1, row + (1 if direction > 0 else -1)))
        self.previewRow(visible[target][0])

    @Slot()
    def toggleCurrent(self):
        if self.previewIndex >= 0:
            self.check(self._index, not self._pairs[self._index].chosen)

    @Slot(int, bool)
    def check(self, index, value):
        if 0 <= index < len(self._pairs):
            self._pairs[index].chosen = value
            self.changed.emit()

    @Slot(bool)
    def checkAll(self, value):
        for _, p in self._view_pairs():
            p.chosen = value
        self.changed.emit()

    @Slot(int, int)
    def pair(self, current, reference):
        """One explicit anchor, with independently matched prefixes/suffixes."""
        a, b = current - 1, reference - 1
        if not self._reference or not self._snapshot or not (0 <= a < len(self._snapshot.cues) and 0 <= b < len(self._reference.cues)):
            self._status = 'Укажите существующие номера реплик в обоих файлах.'
        else:
            before = pair_lines(self._snapshot.cues[:a], self._reference.cues[:b])
            after = pair_lines(self._snapshot.cues[a+1:], self._reference.cues[b+1:])
            for p in after:
                if p.current is not None:
                    p.current += a + 1
                if p.reference is not None:
                    p.reference += b + 1
            self._pairs = before + [Pair(a, b)] + after
            self._index = len(before)
            self._ensure_preview()
            self._status = 'Пара закреплена. Повторно выберите нужные изменения.'
        self.changed.emit()

    @Slot(bool)
    def play(self, reference):
        if self._snapshot and self._reference and 0 <= self._index < len(self._pairs):
            p = self._pairs[self._index]
            index = p.reference if reference else p.current
            if index is not None:
                cue = (self._reference if reference else self._snapshot).cues[index]
                self.backend.media_controller.playRange(cue.start, cue.end)

    @Slot(result=bool)
    def apply(self):
        b = self.backend
        if not b.flush() or not b.flushCard() or not self.canApply:
            return False
        try:
            current_id = b.current.get('id')
            selected = {b.editor.document.cues[i].id for i in b.selection}
            transfer(b.editor, self._snapshot, self._reference, self._pairs, self._fields,
                     translation=b.mode == 'translation', structure=self._structure)
            b.selection = {i for i, c in enumerate(b.editor.document.cues) if c.id in selected}
            b._current = next((i for i, c in enumerate(b.editor.document.cues) if c.id == current_id), min(b._current, b.count-1))
            if b._current < 0 and b.count:
                b._current = 0
            b._anchor = b._current
            if not b.selection and b._current >= 0:
                b.selection = {b._current}
            b._refresh()
            self.refresh()
            self._status = 'Выбранные изменения применены. Их можно отменить одной командой.'
            self.changed.emit()
            return True
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self._status = str(exc)
            self.changed.emit()
            return False


class QualityProfiles(QObject):
    changed = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        try:
            saved = json.loads(backend.settings.value('quality/profiles', '{}'))
            self._profiles = {str(k): validate_profile(v) for k, v in saved.items()}
        except (ValueError, TypeError, AttributeError):
            self._profiles = {}
        self._selected, self._status = '', ''

    @Property('QVariantList', notify=changed)
    def names(self):
        return ['Текущие настройки документа', 'Обычные субтитры'] + list(self._profiles)

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property('QVariantMap', notify=changed)
    def profile(self):
        if self._selected in self._profiles:
            return dict(self._profiles[self._selected])
        if self._selected == 'Обычные субтитры':
            return dict(DEFAULT_PROFILE)
        b = self.backend
        return dict(DEFAULT_PROFILE, **dict(b.reviewSettings, cps=b.cpsLimit, width=b.lineLimit))

    @Slot(str)
    def select(self, name):
        self._selected = name
        self.changed.emit()

    @Slot(str, 'QVariantMap', result=bool)
    def save(self, name, values):
        try:
            name = name.strip()
            if not name or name in self.names[:2] or len(name) > 100:
                raise ValueError('Введите отдельное название профиля (до 100 символов).')
            self._profiles[name] = validate_profile(values)
            self._selected = name
            self.backend.settings.setValue('quality/profiles', json.dumps(self._profiles, ensure_ascii=False))
            self._status = 'Профиль сохранён на этом компьютере.'
            self.changed.emit()
            return True
        except (ValueError, TypeError) as exc:
            self._status = str(exc)
            self.changed.emit()
            return False

    @Slot(str)
    def remove(self, name):
        self._profiles.pop(name, None)
        self.backend.settings.setValue('quality/profiles', json.dumps(self._profiles, ensure_ascii=False))
        self._selected = ''
        self.changed.emit()

    @Slot()
    @Slot('QVariantMap')
    def exportReport(self, options=None):
        b = self.backend
        if not b.flush() or not b.flushCard():
            return
        path, _ = QFileDialog.getSaveFileName(None, 'Сохранить отчёт проверки', 'Проверка.html', 'Веб-страница (*.html);;Таблица (*.csv)')
        if path:
            try:
                rows = findings(b.editor.document, options or self.profile)
                write_report(path, rows, b.title + ' — проверка субтитров')
                self._status = f'Отчёт сохранён. Замечаний: {len(rows)}.'
            except (ValueError, OSError, TypeError) as exc:
                self._status = str(exc)
            self.changed.emit()
