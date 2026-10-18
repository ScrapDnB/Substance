"""Review, audition and atomically apply manual subtitle synchronization."""
from copy import deepcopy

from PySide6.QtCore import QObject, Property, Signal, Slot

from .document import plain_text
from .timecode import format_time, parse_time
from .timing import MAX_TIME, timing_plan


def display_time(value):
    return ('−' if value < 0 else '') + format_time(abs(value))


class TimingController(QObject):
    changed = Signal()
    rowsChanged = Signal()
    requested = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self._snapshot = self._editor = None
        self._kind, self._scope, self._edges = 'shift', 'all', 'both'
        self._delta, self._preview = 0, 0
        self._points, self._plan, self._selected = {}, [], []
        self._rows = []
        self._current = 0
        self._error, self._input_error = '', ''
        backend.changed.connect(self._sync)
        backend.documentReplaced.connect(self.cancel)

    @Slot(str)
    def open(self, kind):
        if self.backend.busy or not self.backend.count or not self.backend.flush():
            return
        self._editor = self.backend.editor
        self._snapshot = deepcopy(self._editor.document)
        self._selected = self.backend._indices()
        self._current = max(0, self.backend._current)
        self._preview = self._current
        self._kind = 'points' if kind == 'points' else 'shift'
        self._scope, self._edges, self._delta = 'all', 'both', 0
        self._points, self._input_error = {}, ''
        self._rebuild()
        self.requested.emit()

    @Property(str, notify=changed)
    def kind(self):
        return self._kind

    @Property(str, notify=changed)
    def scope(self):
        return self._scope

    @Property(int, notify=changed)
    def selectedCount(self):
        return len(self._selected)

    @Property(int, notify=changed)
    def currentNumber(self):
        return self._current + 1

    @Property(int, notify=changed)
    def delta(self):
        return self._delta

    @Property(bool, notify=changed)
    def stale(self):
        return self._snapshot is not None and (self._editor is not self.backend.editor
            or self._snapshot.cues != self.backend.editor.document.cues or bool(self.backend.draft))

    @Property(str, notify=changed)
    def error(self):
        if self.stale:
            return 'Документ изменился. Откройте инструмент заново, чтобы пересчитать результат.'
        return self._input_error or self._error

    @Property(bool, notify=changed)
    def canApply(self):
        return self._snapshot is not None and not self.backend.busy and not self.error and self.changedCount > 0

    @Property(int, notify=changed)
    def changedCount(self):
        if not self._snapshot:
            return 0
        return sum((p['start'], p['end']) != (self._snapshot.cues[p['index']].start, self._snapshot.cues[p['index']].end) for p in self._plan)

    @Property(int, notify=changed)
    def affectedCount(self):
        return len(self._plan)

    @Property('QVariantList', notify=rowsChanged)
    def rows(self):
        return self._rows

    def _row(self, p):
        i = p['index']
        c = self._snapshot.cues[i]
        return dict(p, number=i + 1, text=plain_text(c.output_text).replace('\n', ' '),
                    beforeStart=c.start, beforeEnd=c.end, before=f'{format_time(c.start)} → {format_time(c.end)}',
                    after=f'{display_time(p["start"])} → {display_time(p["end"])}',
                    shift=p['start'] - c.start, endShift=p['end'] - c.end, point=c.id in self._points)

    @Property('QVariantMap', notify=changed)
    def preview(self):
        return next((self._row(p) for p in self._plan if p['index'] == self._preview), {})

    @Property('QVariantList', notify=rowsChanged)
    def points(self):
        if not self._snapshot:
            return []
        return [dict(index=i, number=i + 1, source=format_time(c.start), target=format_time(self._points[c.id]),
                     time=self._points[c.id], shift=self._points[c.id] - c.start)
                for i, c in sorted(enumerate(self._snapshot.cues), key=lambda pair: (pair[1].start, pair[0])) if c.id in self._points]

    def _indices(self):
        if not self._snapshot:
            return []
        if self._scope == 'selected':
            return self._selected
        if self._scope == 'following':
            return list(range(self._current, len(self._snapshot.cues)))
        return list(range(len(self._snapshot.cues)))

    @Slot(str)
    def setScope(self, scope):
        if scope in ('all', 'selected', 'following'):
            self._scope = scope
            self._rebuild()

    @Slot(int, str)
    def setShift(self, delta, edges):
        self._delta, self._edges = delta, edges
        self._rebuild()

    @Slot(int)
    def selectPreview(self, index):
        if index in self._indices():
            self._preview = index
            self._input_error = ''
            self.changed.emit()

    @Slot(str)
    def validateTarget(self, value):
        self._input_error = ''
        try:
            if parse_time(value) > MAX_TIME:
                raise ValueError('Таймкод выходит за допустимый диапазон.')
        except ValueError as exc:
            self._input_error = str(exc)
        self.changed.emit()

    @Slot(int, result=str)
    def formatTime(self, value):
        return format_time(value)

    @Slot(str, int, result=str)
    def nudgeTarget(self, value, amount):
        try:
            return format_time(max(0, min(MAX_TIME, parse_time(value) + amount)))
        except ValueError:
            return value

    @Slot(str)
    def seekTarget(self, value):
        self.validateTarget(value)
        if not self._input_error and self.backend.media_controller.hasMedia:
            self.backend.media_controller.seek(parse_time(value))

    @Slot(str, result=bool)
    def setPoint(self, value):
        if not self._snapshot or self.stale or self._preview not in self._indices():
            return False
        self.validateTarget(value)
        if self._input_error:
            return False
        self._points[self._snapshot.cues[self._preview].id] = parse_time(value)
        self._rebuild()
        return True

    @Slot(int)
    def removePoint(self, index):
        if self._snapshot and 0 <= index < len(self._snapshot.cues):
            self._points.pop(self._snapshot.cues[index].id, None)
            self._rebuild()

    @Slot()
    def clearPoints(self):
        self._points = {}
        self._input_error = ''
        self._rebuild()

    @Slot(int, bool)
    def play(self, index, after):
        if self.stale or not self.backend.media_controller.hasMedia:
            return
        p = next((p for p in self._plan if p['index'] == index), None)
        if p and not (after and (p['error'] or self._error)):
            c = self._snapshot.cues[index]
            self.backend.media_controller.playRange(p['start'] if after else c.start, p['end'] if after else c.end)

    @Slot(result=bool)
    def apply(self):
        if not self.canApply or not self.backend.flush() or not self.canApply:
            return False
        b = self.backend
        plan = list(self._plan)

        def edit(doc):
            for p in plan:
                cue = doc.cues[p['index']]
                if (cue.start, cue.end) != (p['start'], p['end']):
                    cue.start, cue.end = p['start'], p['end']
                    cue.extras.pop('untimed', None)

        try:
            count = self.changedCount
            b.editor.transact('Точечная синхронизация' if self._kind == 'points' else 'Сдвиг времени', edit)
            self.cancel()
            b._refresh()
            b.notify(f'Тайминг обновлён: {count} реплик. Изменения можно отменить одним действием.')
            return True
        except (ValueError, OSError) as exc:
            self._error = str(exc)
            self.changed.emit()
            return False

    @Slot()
    def cancel(self):
        self._snapshot = self._editor = None
        self._plan, self._points = [], {}
        self._rows = []
        self._error, self._input_error = '', ''
        self.rowsChanged.emit()
        self.changed.emit()

    def _sync(self):
        if self._snapshot is not None:
            self.changed.emit()

    def _rebuild(self):
        self._plan, self._error = [], ''
        if self._snapshot:
            indices = self._indices()
            if self._preview not in indices and indices:
                self._preview = indices[0]
            try:
                self._plan = timing_plan(self._snapshot.cues, indices, delta=self._delta, edges=self._edges,
                                         points=self._points if self._kind == 'points' else None)
                invalid = [p for p in self._plan if p['error']]
                if invalid:
                    self._error = f'Некорректных интервалов: {len(invalid)}. Реплика {invalid[0]["index"] + 1}: {invalid[0]["error"]}. Измените параметры.'
                elif not indices:
                    self._error = 'В этой области нет реплик.'
            except ValueError as exc:
                self._error = str(exc)
                self._plan = timing_plan(self._snapshot.cues, indices)
        self._rows = [self._row(p) for p in self._plan]
        self.rowsChanged.emit()
        self.changed.emit()
