"""Qt bridge: document commands, selection, persistence and platform dialogs."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import json
import os
import re
import sys
import math

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Property, QRunnable, QSettings, QStandardPaths, QThreadPool, QTimer, Qt, Signal, Slot, QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog, QDialogButtonBox, QVBoxLayout, QLabel, QKeySequenceEdit

from . import __version__
from .document import Cue, Document, atomic_write, export_document, identity, load_document, parse_ass, parse_srt, parse_txt, plain_text, save_document
from .editor import Editor, quality
from .media import MediaController
from .tasks import SpellingTask, ExtractTask
from .timecode import format_time, parse_time, frame_time
from .platform import reduce_motion

SHORTCUTS = {
    "new": "Ctrl+N", "open": "Ctrl+O", "save": "Ctrl+S", "saveAs": "Ctrl+Shift+S", "export": "Ctrl+E",
    "undo": "Ctrl+Z", "redo": "Ctrl+Shift+Z", "find": "Ctrl+F", "replace": "Ctrl+H", "apply": "Ctrl+Return",
    "add": "Ctrl+Return", "newLine": "Ctrl+Shift+Return", "duplicate": "Ctrl+D", "split": "Ctrl+Shift+D", "merge": "Ctrl+J",
    "previous": "Alt+Up", "next": "Alt+Down", "play": "Ctrl+Space", "playLine": "Alt+Space",
    "setStart": "Ctrl+1", "setEnd": "Ctrl+2", "frameBack": "Alt+Left", "frameForward": "Alt+Right",
    "shift": "Ctrl+Shift+T", "copyLines": "Ctrl+Shift+C", "pasteLines": "Ctrl+Shift+V", "deleteLines": "Ctrl+Shift+Backspace",
}


class LoadSignals(QObject):
    finished = Signal(object, str)
    failed = Signal(str)


class LoadTask(QRunnable):
    def __init__(self, path, encoding):
        super().__init__()
        self.path, self.encoding = path, encoding
        self.signals = LoadSignals()

    def run(self):
        try:
            self.signals.finished.emit(load_document(self.path, self.encoding), self.path)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class CueModel(QAbstractListModel):
    ROLE_NAMES = ["sourceIndex", "number", "startTime", "endTime", "character", "cueText", "originalText", "translatedText", "reviewStatus", "cps", "warning", "issues", "selected", "comment"]
    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.visible: list[int] = []
        self.cache = []
        self.roles = {Qt.ItemDataRole.UserRole + i + 1: name.encode() for i, name in enumerate(self.ROLE_NAMES)}

    def roleNames(self):
        return self.roles

    def rowCount(self, parent=QModelIndex()):
        return len(self.visible)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or index.row() >= len(self.cache):
            return None
        name = self.roles.get(role, b"").decode()
        return self.cache[index.row()].get(name)

    def rebuild(self):
        self.beginResetModel()
        self.visible, self.cache = [], []
        backend = self.backend
        doc = backend.editor.document
        for i, cue in enumerate(doc.cues):
            info = backend.cue_quality(i)
            if not backend.matches(cue, info):
                continue
            self.visible.append(i)
            self.cache.append({"sourceIndex": i, "number": i + 1, "startTime": format_time(cue.start), "endTime": format_time(cue.end), "character": cue.character, "cueText": plain_text(cue.output_text).replace("\n", "  ↵  "), "originalText": plain_text(cue.original).replace("\n", "  ↵  "), "translatedText": plain_text(cue.translation or "").replace("\n", "  ↵  "), "reviewStatus": cue.status, "cps": info["cps"], "warning": info["warning"], "issues": "\n".join(info["messages"]), "selected": i in backend.selection, "comment": cue.comment})
        self.endResetModel()

    def update_selection(self):
        role = next(k for k, v in self.roles.items() if v == b"selected")
        for row, source in enumerate(self.visible):
            selected = source in self.backend.selection
            if self.cache[row]["selected"] != selected:
                self.cache[row]["selected"] = selected
                self.dataChanged.emit(self.index(row), self.index(row), [role])


class Backend(QObject):
    changed = Signal()
    currentChanged = Signal()
    preferencesChanged = Signal()
    previewChanged = Signal()
    playbackChanged = Signal()
    searchRequested = Signal(bool)
    shortcutRequested = Signal()
    toast = Signal(str)
    centerWaveform = Signal()
    focusEditor = Signal()
    spellingChanged = Signal()
    highlightWord = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = Editor()
        self.media_controller = MediaController(self)
        self.media_controller.error.connect(self.show_error)
        self.media_controller.metadataReady.connect(self._media_metadata)
        self.media_controller.positionChanged.connect(self.playbackChanged)
        data_dir = os.environ.get("SUBSTANCE_DATA_DIR") or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(self.data_dir / "settings.ini"), QSettings.Format.IniFormat)
        self.recovery_path = self.data_dir / f"recovery-{os.getpid()}.substance"
        self.path = ""
        self._mode = "timing"
        self._current = -1
        self.selection: set[int] = set()
        self._anchor = -1
        self.draft = {}
        self._busy = False
        self._spelling_busy = False
        self._spelling_results = []
        self._spelling_revision = None
        self._filter, self._search, self._character_filter = "all", "", ""
        self._pattern = None
        self._preview = self.editor.document.ass_text()
        self._message = "Создайте документ или откройте субтитры"
        self._computed_key = None
        self._quality_cache = []
        self._counts_cache = {}
        self._characters_cache = []
        self._theme = self.settings.value("theme", "system")
        self._motion = self.settings.value("motion", True, type=bool) and not reduce_motion()
        self._encoding = self.settings.value("importEncoding", "auto")
        self._cps_limit = self.settings.value("cpsLimit", 20, type=int)
        self._line_limit = self.settings.value("lineLimit", 42, type=int)
        default_shortcuts = {**SHORTCUTS, **({"redo": "Ctrl+Y"} if sys.platform == "win32" else {"play": "Ctrl+Shift+Space"} if sys.platform == "darwin" else {})}
        try:
            self._shortcuts = {**default_shortcuts, **json.loads(self.settings.value("shortcuts", "{}"))}
            self._recents = json.loads(self.settings.value("recents", "[]"))
        except (ValueError, TypeError):
            self._shortcuts, self._recents = default_shortcuts, []
        self.model = CueModel(self)
        self._stage_timer = QTimer(self, interval=550, singleShot=True)
        self._stage_timer.timeout.connect(self.flush)
        self._preview_timer = QTimer(self, interval=150, singleShot=True)
        self._preview_timer.timeout.connect(self._update_preview)
        self._autosave_timer = QTimer(self, interval=15000)
        self._autosave_timer.timeout.connect(self.autosave)
        self._autosave_timer.start()
        self.model.rebuild()

    @Property(QObject, constant=True)
    def cues(self):
        return self.model

    @Property(QObject, constant=True)
    def media(self):
        return self.media_controller

    @Property(str, constant=True)
    def version(self):
        return __version__

    @Property(bool, constant=True)
    def isMac(self):
        return sys.platform == "darwin"

    @Property(bool, notify=changed)
    def dirty(self):
        return self.editor.dirty or bool(self.draft)

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def title(self):
        return Path(self.path).name if self.path else "Новые субтитры"

    @Property(str, notify=changed)
    def documentPath(self):
        return self.path

    @Property(str, notify=changed)
    def message(self):
        return self._message

    @Property(str, notify=currentChanged)
    def mode(self):
        return self._mode

    @Property(int, notify=changed)
    def count(self):
        return len(self.editor.document.cues)

    @Property(int, notify=changed)
    def visibleCount(self):
        return len(self.model.visible)

    @Property(int, notify=currentChanged)
    def currentIndex(self):
        return self._current

    @Property(int, notify=currentChanged)
    def currentVisible(self):
        return self.model.visible.index(self._current) if self._current in self.model.visible else -1

    @Property(int, notify=changed)
    def selectionCount(self):
        return len(self.selection)

    @Property(float, notify=changed)
    def fps(self):
        return self.editor.document.fps

    @Property(str, notify=changed)
    def encoding(self):
        return self.editor.document.encoding

    @Property(str, notify=changed)
    def activeFilter(self):
        return self._filter

    @Property(str, notify=changed)
    def characterFilter(self):
        return self._character_filter

    @Property(str, notify=changed)
    def search(self):
        return self._search

    @Property('QVariantMap', notify=changed)
    def counts(self):
        self._compute()
        return self._counts_cache

    @Property('QVariantList', notify=changed)
    def characters(self):
        self._compute()
        return self._characters_cache

    @Property('QVariantList', notify=changed)
    def recentFiles(self):
        return self._recents

    @Property(bool, notify=changed)
    def canUndo(self):
        return bool(self.editor.undo_stack)

    @Property(bool, notify=changed)
    def canRedo(self):
        return bool(self.editor.redo_stack)

    @Property(str, notify=previewChanged)
    def previewScript(self):
        return self._preview

    @Property(str, notify=playbackChanged)
    def fallbackText(self):
        position = self.media_controller.position
        return "\n".join(plain_text(c.output_text) for c in self.editor.document.cues if not c.comment and c.start <= position < c.end)

    @Property('QVariantList', notify=currentChanged)
    def neighbors(self):
        return [value for i in (self._current - 1, self._current + 1) if 0 <= i < self.count for value in (self.editor.document.cues[i].start, self.editor.document.cues[i].end)]

    @Property('QVariantList', notify=currentChanged)
    def contextLines(self):
        return [{"number": i + 1, "character": self.editor.document.cues[i].character, "text": plain_text(self.editor.document.cues[i].output_text), "active": i == self._current, "sourceIndex": i} for i in range(max(0, self._current - 1), min(self.count, self._current + 2))]

    @Property('QVariantMap', notify=changed)
    def current(self):
        if not 0 <= self._current < self.count:
            return {"exists": False, "start": 0, "end": 2000, "startTime": "00:00:00.000", "endTime": "00:00:02.000", "original": "", "editText": "", "character": "", "status": "draft", "issues": [], "cps": 0, "comment": False}
        cue = self.editor.document.cues[self._current]
        info = self.cue_quality(self._current)
        text = (cue.translation or "") if self._mode == "translation" else cue.output_text
        text = self.draft.get("translation", self.draft.get("text", text))
        return {"exists": True, "id": cue.id, "number": self._current + 1, "start": cue.start, "end": cue.end, "startTime": self.draft.get("start", format_time(cue.start)), "endTime": self.draft.get("end", format_time(cue.end)), "duration": (cue.end - cue.start) / 1000, "character": self.draft.get("character", cue.character), "original": cue.original.replace(r"\N", "\n"), "editText": text.replace(r"\N", "\n"), "status": cue.status, "comment": cue.comment, "issues": info["messages"], "cps": info["cps"], "maxLine": info["maxLine"]}

    @Property(str, notify=preferencesChanged)
    def theme(self):
        return self._theme

    @Property(bool, notify=preferencesChanged)
    def motion(self):
        return self._motion

    @Property(int, notify=preferencesChanged)
    def cpsLimit(self):
        return self._cps_limit

    @Property(int, notify=preferencesChanged)
    def lineLimit(self):
        return self._line_limit

    @Property('QVariantMap', notify=preferencesChanged)
    def shortcuts(self):
        return self._shortcuts

    @Property(bool, notify=spellingChanged)
    def spellingBusy(self):
        return self._spelling_busy

    @Property('QVariantList', notify=spellingChanged)
    def spellingResults(self):
        return self._spelling_results

    @Slot(str)
    def checkSpelling(self, language):
        if self._spelling_busy or not self.flush():
            return
        self._spelling_busy = True
        self._spelling_results = []
        self._spelling_revision = (id(self.editor), self.editor.revision)
        ignored = self.settings.value("ignoredWords", [], type=list) + self.characters
        task = SpellingTask([(i, c.output_text) for i, c in enumerate(self.editor.document.cues) if not c.comment], language, ignored)
        self._spelling_task = task
        task.signals.completed.connect(self._spelling_done)
        task.signals.failed.connect(self._spelling_error)
        self.spellingChanged.emit()
        QThreadPool.globalInstance().start(task)

    def _spelling_done(self, results):
        self._spelling_task = None
        self._spelling_busy = False
        if self._spelling_revision == (id(self.editor), self.editor.revision):
            self._spelling_results = results
        else:
            self.notify("Текст изменился во время проверки. Запустите проверку ещё раз.")
        self.spellingChanged.emit()

    def _spelling_error(self, error):
        self._spelling_task = None
        self._spelling_busy = False
        self.spellingChanged.emit()
        self.show_error(error)

    @Slot(int, str)
    def locateSpelling(self, index, word):
        if self.select(index, 0):
            self.highlightWord.emit(word)

    @Slot(str)
    def ignoreSpelling(self, word):
        ignored = self.settings.value("ignoredWords", [], type=list)
        self.settings.setValue("ignoredWords", list(dict.fromkeys(ignored + [word.lower()])))
        self._spelling_results = [r for r in self._spelling_results if r["word"].lower() != word.lower()]
        self.spellingChanged.emit()

    @Slot(int, str, str)
    def correctSpelling(self, index, word, replacement):
        if not self._spelling_revision == (id(self.editor), self.editor.revision):
            self.show_error("Проверьте орфографию ещё раз после изменения документа")
            return
        if self._guard(lambda: self.editor.replace(r"\b" + re.escape(word) + r"\b", replacement, [index], regex=True, case_sensitive=True)):
            self._spelling_results = [r for r in self._spelling_results if not (r["index"] == index and r["word"] == word)]
            self._spelling_revision = (id(self.editor), self.editor.revision)
            self.spellingChanged.emit()

    @Slot()
    def importEmbedded(self):
        if self._busy:
            return
        path, _ = QFileDialog.getOpenFileName(None, "Импорт субтитров из видео", "", "Видео (*.mkv *.mp4 *.mov *.webm)")
        if not path or not self._confirm_unsaved():
            return
        track, ok = QInputDialog.getInt(None, "Дорожка субтитров", "Номер дорожки субтитров (1 — первая)", 1, 1, 100)
        if not ok:
            return
        self._busy = True
        self.changed.emit()
        task = ExtractTask(path, track - 1)
        self._extract_task = task
        task.signals.failed.connect(self._load_error)
        task.signals.completed.connect(self._embedded_ready)
        QThreadPool.globalInstance().start(task)

    def _embedded_ready(self, doc):
        self._extract_task = None
        self._set_document(doc, "")
        self.editor.saved_revision = -1
        self.media_controller.open(doc.media["path"])
        self.changed.emit()
        self.notify(f"Извлечено реплик: {self.count}")

    def _compute(self):
        key = (id(self.editor.document), self.editor.revision, self._cps_limit, self._line_limit)
        if key == self._computed_key:
            return
        cues = self.editor.document.cues
        self._quality_cache = [quality(c, next_cue=cues[i + 1] if i + 1 < len(cues) else None, cps_limit=self._cps_limit, line_limit=self._line_limit) for i, c in enumerate(cues)]
        self._counts_cache = {"all": len(cues), "missing": sum(c.translation in (None, "") for c in cues if not c.comment), "review": sum(c.status != "done" for c in cues), "done": sum(c.status == "done" for c in cues), "warnings": sum(q["warning"] for q in self._quality_cache)}
        self._characters_cache = sorted({c.character for c in cues if c.character})
        self._computed_key = key

    def cue_quality(self, index):
        self._compute()
        return self._quality_cache[index]

    def matches(self, cue, info):
        if self._filter == "missing" and cue.translation not in (None, ""):
            return False
        if self._filter == "review" and cue.status == "done":
            return False
        if self._filter == "done" and cue.status != "done":
            return False
        if self._filter == "warnings" and not info["warning"]:
            return False
        if self._character_filter and cue.character != self._character_filter:
            return False
        return not self._pattern or self._pattern.search(cue.original + "\n" + cue.output_text) is not None

    def _refresh(self, current=True):
        self._current = min(self._current, self.count - 1)
        self.selection = {i for i in self.selection if i < self.count}
        self.model.rebuild()
        self.changed.emit()
        if current:
            self.currentChanged.emit()
        self._preview_timer.start()

    def _guard(self, command, current=True):
        if not self.flush():
            return False
        try:
            command()
            media_path = self.editor.document.media.get("path", "")
            if media_path != self.media_controller.path:
                if media_path and Path(media_path).is_file():
                    self.media_controller.open(media_path)
                else:
                    self.media_controller.clear()
            self._refresh(current)
            return True
        except (ValueError, IndexError, OSError, TypeError, re.error) as exc:
            self.show_error(str(exc))
            return False

    @Slot(str)
    def show_error(self, value):
        self._message = value
        self.toast.emit(value)
        self.changed.emit()

    def notify(self, value):
        self._message = value
        self.toast.emit(value)
        self.changed.emit()

    @Slot(str, str)
    def stage(self, key, value):
        if not 0 <= self._current < self.count:
            return
        cue = self.editor.document.cues[self._current]
        if key == "text":
            key = "translation" if self._mode == "translation" or cue.translation is not None else "text"
            value = value.replace("\n", r"\N")
        original = getattr(cue, key, None)
        if key in ("start", "end"):
            original = format_time(original)
        if value == original:
            self.draft.pop(key, None)
        else:
            self.draft[key] = value
        self.changed.emit()
        if key not in ("start", "end"):
            self._stage_timer.start()
        self._preview_timer.start()

    @Slot(result=bool)
    def flush(self):
        self._stage_timer.stop()
        if not self.draft:
            return True
        try:
            values = dict(self.draft)
            for key in ("start", "end"):
                if key in values:
                    values[key] = parse_time(values[key])
            self.editor.update(self._current, **values)
            self.draft.clear()
            self._refresh(current=False)
            return True
        except (ValueError, IndexError) as exc:
            self.show_error(str(exc))
            return False

    def _update_preview(self):
        doc = self.editor.document
        if self.draft and self._current >= 0:
            doc = deepcopy(doc)
            for key, value in self.draft.items():
                if key not in ("start", "end"):
                    setattr(doc.cues[self._current], key, value)
        self._preview = doc.ass_text()
        self.previewChanged.emit()
        self.playbackChanged.emit()

    @Slot(int, int, result=bool)
    def select(self, index, modifiers=0):
        if not 0 <= index < self.count or not self.flush():
            return False
        shift = modifiers & Qt.KeyboardModifier.ShiftModifier.value
        control = modifiers & Qt.KeyboardModifier.ControlModifier.value
        if shift and self._anchor in self.model.visible and index in self.model.visible:
            a, b = self.model.visible.index(self._anchor), self.model.visible.index(index)
            self.selection = set(self.model.visible[min(a, b):max(a, b) + 1])
        elif control:
            if index in self.selection:
                self.selection.remove(index)
            else:
                self.selection.add(index)
            self._anchor = index
        else:
            self.selection = {index}
            self._anchor = index
        self._current = index
        self.model.update_selection()
        self.currentChanged.emit()
        self.changed.emit()
        self.centerWaveform.emit()
        return True

    @Slot()
    def selectAll(self):
        self.selection = set(self.model.visible)
        self.model.update_selection()
        self.changed.emit()

    @Slot(int)
    def navigate(self, delta):
        visible = self.model.visible
        if visible:
            row = self.currentVisible
            next_row = min(len(visible) - 1, max(0, row + delta))
            if self.select(visible[next_row], 0):
                self.focusEditor.emit()

    @Slot(str)
    def setMode(self, value):
        if self.flush() and value in ("timing", "translation"):
            self._mode = value
            self.currentChanged.emit()
            self.focusEditor.emit()

    @Slot(str)
    def setFilter(self, value):
        if self.flush():
            self._filter = value
            self._refresh()

    @Slot(str, bool, bool, result=bool)
    def setSearch(self, text, case_sensitive=False, regex=False):
        try:
            pattern = re.compile(text if regex else re.escape(text), 0 if case_sensitive else re.IGNORECASE) if text else None
        except re.error as exc:
            self.show_error("Ошибка регулярного выражения: " + str(exc))
            return False
        if not self.flush():
            return False
        self._search, self._pattern = text, pattern
        self._refresh()
        return True

    @Slot(str)
    def setCharacterFilter(self, value):
        if self.flush():
            self._character_filter = value
            self._refresh()

    def _indices(self, all_lines=False):
        if all_lines:
            return list(range(self.count))
        return sorted(self.selection or ({self._current} if self._current >= 0 else set()))

    @Slot()
    def addLine(self):
        def add():
            self._current = self.editor.add(self._current)
            self.selection = {self._current}
            self._filter, self._search, self._pattern = "all", "", None
        if self._guard(add):
            self.centerWaveform.emit()
            self.focusEditor.emit()

    @Slot()
    def deleteLines(self):
        def command():
            indices = self._indices()
            self.editor.delete(indices)
            self._current = min(min(indices, default=0), self.count - 1)
            self.selection = {self._current} if self._current >= 0 else set()
        self._guard(command)

    @Slot()
    def duplicateLines(self):
        def command():
            self._current = self.editor.duplicate(self._indices())
            self.selection = {self._current} if self._current >= 0 else set()
        self._guard(command)

    @Slot(int)
    def splitLine(self, cursor):
        if not self.flush() or self._current < 0:
            return
        text = self.editor.document.cues[self._current].output_text.replace(r"\N", "\n")
        raw_cursor = len(text[:cursor].replace("\n", r"\N"))
        self._guard(lambda: self.editor.split(self._current, raw_cursor, self.media_controller.position, translation_mode=self._mode == "translation"))

    @Slot()
    def mergeLines(self):
        def command():
            indices = self._indices()
            self.editor.merge(indices)
            self._current = min(indices)
            self.selection = {self._current}
        self._guard(command)

    @Slot()
    def undo(self):
        if self._guard(self.editor.undo):
            self.notify("Правка отменена")

    @Slot()
    def redo(self):
        if self._guard(self.editor.redo):
            self.notify("Правка повторена")

    @Slot(bool)
    def apply(self, next_line=False):
        if not self.flush() or self._current < 0:
            return
        if self._mode == "translation" and not self.editor.document.cues[self._current].translation:
            self.show_error("Сначала введите перевод")
            return
        if self._guard(lambda: self.editor.update(self._current, status="done")):
            if next_line:
                self.navigate(1)
            else:
                self.notify("Реплика применена")

    @Slot(int, int)
    def setRange(self, start, end):
        self._guard(lambda: self.editor.update(self._current, start=start, end=end))

    @Slot(str)
    def setEdge(self, edge):
        self._guard(lambda: self.editor.update(self._current, **{edge: self.media_controller.framePosition}))

    @Slot(int)
    def stepFrame(self, direction):
        position = self.media_controller.framePosition
        frame = round(position * self.fps / 1000) + direction
        self.media_controller.player.pause()
        self.media_controller.seek(math.ceil(max(0, frame) * 1000 / self.fps))

    @Slot(bool)
    def playCurrent(self, loop=False):
        if self.flush() and 0 <= self._current < self.count:
            c = self.editor.document.cues[self._current]
            self.media_controller.playRange(c.start, c.end, loop)

    @Slot()
    def seekCurrent(self):
        if self._current >= 0:
            self.media_controller.seek(self.editor.document.cues[self._current].start)

    @Slot(int, str, bool)
    def shift(self, delta, edges, all_lines=False):
        self._guard(lambda: self.editor.shift(self._indices(all_lines), delta, edges))

    @Slot(str, str, bool)
    def batch(self, action, value, all_lines=False):
        if action == "comment":
            parsed = value == "true"
        elif action == "lead":
            parsed = [int(v) for v in value.split(",")]
        else:
            parsed = value
        def command():
            selected_ids = {self.editor.document.cues[i].id for i in self._indices()}
            current_id = self.editor.document.cues[self._current].id if self._current >= 0 else ""
            self.editor.batch(self._indices(all_lines), action, parsed)
            if action == "sort":
                self.selection = {i for i, c in enumerate(self.editor.document.cues) if c.id in selected_ids}
                self._current = next((i for i, c in enumerate(self.editor.document.cues) if c.id == current_id), -1)
        self._guard(command)

    @Slot(str, str, bool, bool, bool)
    def replace(self, text, replacement, regex, case_sensitive, selected_only):
        def command():
            count = self.editor.replace(text, replacement, self._indices() if selected_only else list(range(self.count)), regex=regex, case_sensitive=case_sensitive)
            self.notify(f"Заменено: {count}")
        self._guard(command)

    @Slot()
    def copyLines(self):
        if not self.flush():
            return
        doc = self.editor.document
        cues = [doc.cues[i] for i in self._indices()]
        mime = QMimeData()
        payload = doc.to_dict()
        payload["cues"] = [asdict(c) for c in cues]
        mime.setData("application/x-substance-cues", json.dumps(payload, ensure_ascii=False).encode())
        mime.setText("\n".join(c.ass_line() for c in cues))
        QGuiApplication.clipboard().setMimeData(mime)
        self.notify(f"Скопировано реплик: {len(cues)}")

    @Slot()
    def pasteLines(self):
        def paste():
            mime = QGuiApplication.clipboard().mimeData()
            if mime.hasFormat("application/x-substance-cues"):
                incoming = Document.from_dict(json.loads(bytes(mime.data("application/x-substance-cues"))))
            else:
                text = mime.text()
                incoming = parse_ass("[Events]\nFormat: " + ", ".join(self.editor.document.cues[0].field_order if self.count else ["Layer", "Start", "End", "Style", "Name", "MarginL", "MarginR", "MarginV", "Effect", "Text"]) + "\n" + text) if text.startswith(("Dialogue:", "Comment:")) else parse_srt(text) if " --> " in text else parse_txt(text)
            def edit(doc):
                for c in incoming.cues:
                    c.id = identity("frag")
                doc.source_lines.update(incoming.source_lines)
                doc.cues[self._current + 1:self._current + 1] = incoming.cues
            self.editor.transact("Вставка реплик", edit)
        self._guard(paste)

    @Slot(str, result=str)
    def shortcutLabel(self, action):
        return QKeySequence(self._shortcuts.get(action, "")).toString(QKeySequence.SequenceFormat.NativeText)

    @Slot(str, str, result=bool)
    def setShortcut(self, action, sequence):
        parsed = QKeySequence(sequence)
        normalized = parsed.toString(QKeySequence.SequenceFormat.PortableText)
        if not normalized or parsed.isEmpty():
            self.show_error("Некорректное сочетание клавиш")
            return False
        conflicts = [key for key, value in self._shortcuts.items() if value == normalized and key != action and key != "add"]
        if conflicts:
            self.show_error("Это сочетание уже используется: " + ", ".join(conflicts))
            return False
        self._shortcuts[action] = normalized
        self.settings.setValue("shortcuts", json.dumps(self._shortcuts))
        self.preferencesChanged.emit()
        return True

    @Slot()
    def resetShortcuts(self):
        self._shortcuts = dict(SHORTCUTS)
        if sys.platform == "win32":
            self._shortcuts["redo"] = "Ctrl+Y"
        elif sys.platform == "darwin":
            self._shortcuts["play"] = "Ctrl+Shift+Space"
        self.settings.setValue("shortcuts", "{}")
        self.preferencesChanged.emit()

    @Slot(str)
    def editShortcutDialog(self, action):
        dialog = QDialog()
        dialog.setWindowTitle("Горячая клавиша")
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel("Нажмите новое сочетание клавиш"))
        edit = QKeySequenceEdit(QKeySequence(self._shortcuts.get(action, "")))
        edit.setMaximumSequenceLength(1)
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.setShortcut(action, edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    @Slot(str, str)
    def preference(self, name, value):
        if name == "theme" and value in ("system", "light", "dark"):
            self._theme = value
            scheme = Qt.ColorScheme.Unknown if value == "system" else Qt.ColorScheme.Dark if value == "dark" else Qt.ColorScheme.Light
            QGuiApplication.styleHints().setColorScheme(scheme)
        elif name == "motion":
            self._motion = value == "true" and not reduce_motion()
            value = self._motion
        elif name == "cpsLimit":
            self._cps_limit = max(1, min(100, int(value)))
            value = self._cps_limit
        elif name == "lineLimit":
            self._line_limit = max(10, min(200, int(value)))
            value = self._line_limit
        elif name == "importEncoding":
            self._encoding = value
        else:
            return
        self.settings.setValue(name, value)
        self.preferencesChanged.emit()
        self._refresh()

    @Slot(float, str)
    def documentSettings(self, fps, encoding):
        def apply(doc):
            doc.fps, doc.encoding, doc.bom = fps, encoding, False
            doc.metadata["fps_source"] = "manual"
        self._guard(lambda: self.editor.transact("Настройки документа", apply))

    def _confirm_unsaved(self):
        if not self.flush():
            return False
        if not self.dirty:
            return True
        answer = QMessageBox.question(None, "Сохранить изменения?", f"В «{self.title}» есть несохранённые изменения.", QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save)
        if answer == QMessageBox.StandardButton.Save:
            return self.save()
        return answer == QMessageBox.StandardButton.Discard

    @Slot()
    def newDocument(self):
        if self._confirm_unsaved():
            self._set_document(Document(), "")
            self.media_controller.clear()

    def _set_document(self, document, path):
        self.editor = Editor(document)
        self.path = path
        self.draft.clear()
        self._filter, self._search, self._pattern = "all", "", None
        self._character_filter = ""
        self._current = 0 if document.cues else -1
        self.selection = {0} if document.cues else set()
        self._busy = False
        self._refresh()
        self.centerWaveform.emit()
        self._remove_recovery()

    @Slot()
    def openDialog(self):
        path, _ = QFileDialog.getOpenFileName(None, "Открыть субтитры", str(Path(self.path).parent) if self.path else "", "Субтитры (*.ass *.ssa *.srt *.vtt *.txt *.substance)")
        if path:
            self.openPath(path)

    @Slot(str)
    def openPath(self, path):
        if self._busy or not self._confirm_unsaved():
            return
        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()
        self._busy = True
        self.changed.emit()
        task = LoadTask(path, self._encoding)
        task.signals.finished.connect(self._loaded)
        task.signals.failed.connect(self._load_error)
        QThreadPool.globalInstance().start(task)

    def _loaded(self, doc, path):
        self._set_document(doc, path if Path(path).suffix.lower() in (".ass", ".substance") else "")
        self._recents = [path] + [p for p in self._recents if p != path][:9]
        self.settings.setValue("recents", json.dumps(self._recents))
        media_path = doc.media.get("path", "")
        if media_path and Path(media_path).is_file():
            self.media_controller.open(media_path)
        else:
            self.media_controller.clear()
        self.notify(f"Открыто реплик: {self.count}" + (f" · Предупреждений импорта: {len(doc.warnings)}" if doc.warnings else ""))
        if doc.warnings:
            QMessageBox.information(None, "Замечания импорта", "\n".join(doc.warnings[:12]))

    def _load_error(self, value):
        self._extract_task = None
        self._busy = False
        self.show_error(value)

    @Slot(result=bool)
    def save(self):
        if not self.flush():
            return False
        if not self.path:
            return self.saveAs()
        try:
            save_document(self.editor.document, self.path)
            self.editor.mark_saved()
            self._remove_recovery()
            self.notify("Сохранено")
            return True
        except (ValueError, OSError) as exc:
            self.show_error("Не удалось сохранить: " + str(exc))
            return False

    @Slot(result=bool)
    def saveAs(self):
        if not self.flush():
            return False
        path, selected = QFileDialog.getSaveFileName(None, "Сохранить субтитры", self.path or "Новые субтитры.ass", "ASS (*.ass);;Проект Substance (*.substance)")
        if not path:
            return False
        if not Path(path).suffix:
            path += ".substance" if "Substance" in selected else ".ass"
        try:
            save_document(self.editor.document, path)
            self.path = path
            self.editor.mark_saved()
            self._remove_recovery()
            self.notify("Сохранено")
            return True
        except (ValueError, OSError) as exc:
            self.show_error("Не удалось сохранить: " + str(exc))
            return False

    @Slot(bool)
    def exportDialog(self, originals=False):
        if not self.flush():
            return
        name = str(Path(self.path).with_suffix(".ass")) if self.path else "Субтитры.ass"
        path, selected = QFileDialog.getSaveFileName(None, "Экспорт оригинала" if originals else "Экспорт субтитров", name, "ASS (*.ass);;SubRip (*.srt);;WebVTT (*.vtt);;Текст (*.txt)")
        if path:
            if not Path(path).suffix:
                path += re.search(r"\*([.][a-z]+)", selected)[1]
            # A plain export over the actively edited ASS would invalidate its sidecar.
            if self.path and Path(path).resolve() == Path(self.path).resolve():
                if originals:
                    self.show_error("Для экспорта оригинала выберите другой файл")
                    return
                self.save()
                return
            try:
                export_document(self.editor.document, path, originals=originals)
                self.notify("Экспорт завершён")
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))

    @Slot()
    def openMedia(self):
        path, _ = QFileDialog.getOpenFileName(None, "Открыть видео или аудио", "", "Медиа (*.mkv *.mp4 *.mov *.avi *.webm *.m4v *.wav *.mp3 *.flac *.m4a *.ogg *.aac);;Все файлы (*)")
        if path:
            self.openMediaPath(path)

    @Slot(str)
    def openMediaPath(self, path):
        if path.startswith("file:"):
            path = QUrl(path).toLocalFile()
        if self.flush() and Path(path).is_file():
            self.editor.transact("Подключение медиа", lambda d: d.media.update(path=path))
            self.media_controller.open(path)
            self._refresh()

    def _media_metadata(self, data):
        fps = data.get("fps", 0)
        if 1 <= fps <= 120 and self.editor.document.metadata.get("fps_source") != "manual":
            self.editor.transact("Частота кадров видео", lambda d: (setattr(d, "fps", round(fps, 6)), d.metadata.update(fps_source="video")))
            self.changed.emit()

    @Slot()
    def openExample(self):
        path = Path(__file__).parent / "resources" / "example.ass"
        if self._confirm_unsaved():
            self._set_document(load_document(path), "")
            self.editor.saved_revision = -1
            self.media_controller.clear()
            self.changed.emit()
            self.notify("Пример открыт как новый документ")

    @Slot()
    def showImportWarnings(self):
        warnings = self.editor.document.warnings
        QMessageBox.information(None, "Замечания импорта", "\n".join(warnings) if warnings else "Файл импортирован без замечаний.")

    @Slot()
    def about(self):
        QMessageBox.about(None, "Substance", f"Substance {__version__}\n\nРедактор ASS для тайминга и перевода.\nPython · Qt Quick · FFmpeg · libass\n\nПредварительная версия.\nГорячие клавиши доступны в меню и настройках.")

    @Slot(result=bool)
    def requestClose(self):
        if self._confirm_unsaved():
            self._remove_recovery()
            return True
        return False

    def _remove_recovery(self):
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError:
            pass

    @Slot()
    def autosave(self):
        if not self.dirty:
            return
        data = self.editor.document.to_dict()
        data["recovery_path"] = self.path
        data["recovery_pid"] = os.getpid()
        data["recovery_draft"] = self.draft
        data["recovery_current"] = self._current
        data["recovery_mode"] = self._mode
        try:
            atomic_write(self.recovery_path, json.dumps(data, ensure_ascii=False).encode("utf-8"))
        except OSError as exc:
            self.show_error("Не удалось записать автосохранение: " + str(exc))

    def restore_recovery(self):
        candidates = sorted(self.data_dir.glob("recovery-*.substance"), key=lambda p: p.stat().st_mtime, reverse=True)
        for path in candidates:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                pid = data.get("recovery_pid", 0)
                if pid and pid != os.getpid():
                    try:
                        os.kill(pid, 0)
                        continue
                    except OSError:
                        pass
                if QMessageBox.question(None, "Восстановить работу?", "Найдено автосохранение после незавершённого сеанса. Восстановить изменения?", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
                    self._set_document(Document.from_dict({k: v for k, v in data.items() if not k.startswith("recovery_")}), data.get("recovery_path", ""))
                    self.editor.saved_revision = -1
                    self._current = min(max(0, data.get("recovery_current", 0)), self.count - 1)
                    self.selection = {self._current} if self._current >= 0 else set()
                    self.draft = data.get("recovery_draft", {})
                    self._mode = data.get("recovery_mode", "timing")
                    if self._mode not in ("timing", "translation"):
                        self._mode = "timing"
                    media_path = self.editor.document.media.get("path", "")
                    if media_path and Path(media_path).is_file():
                        self.media_controller.open(media_path)
                    self._refresh()
                    self.notify("Работа восстановлена; сохраните документ")
                path.unlink(missing_ok=True)
                break
            except (ValueError, OSError, TypeError, KeyError):
                continue

    def shutdown(self):
        for name in ("_spelling_task", "_extract_task"):
            task = getattr(self, name, None)
            if task:
                task.cancel()
        self.settings.sync()
        self.media_controller.shutdown()
        QThreadPool.globalInstance().waitForDone(5000)
