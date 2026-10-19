"""Qt bridge: document commands, selection, persistence and platform dialogs."""
from __future__ import annotations
from copy import copy
from dataclasses import asdict
from pathlib import Path
import json
import os
import re
import sys

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Property, QRunnable, QSettings, QStandardPaths, QThreadPool, QTimer, Qt, Signal, Slot, QMimeData, QUrl
from PySide6.QtGui import QGuiApplication, QKeySequence
from PySide6.QtWidgets import QFileDialog, QMessageBox, QInputDialog, QDialog, QDialogButtonBox, QVBoxLayout, QLabel, QKeySequenceEdit

from . import __version__
from .document import Document, atomic_write, export_document, identity, load_document, parse_ass, parse_srt, parse_txt, plain_text, save_document
from .ass_tags import inventory, remove_document_tags
from .ass_highlighter import AssHighlighter
from .ass_formatting import selection_state, toggle_format, style_states
from .ass_inheritance import inherit_formatting
from .editor import Editor, quality
from .repositories import LocalDocumentRepository
from .online import OnlineController
from .media import MediaController
from .tasks import SpellingTask, ExtractTask
from .timecode import format_time, parse_time
from .platform import reduce_motion
from .project import sync_characters
from .shortcuts import LayoutShortcuts
from .images import load_image, encode_image, decode_image, crop_image
from PySide6.QtGui import QImage
import difflib
import html

SHORTCUTS = {
    "new": "Ctrl+N", "open": "Ctrl+O", "save": "Ctrl+S", "saveAs": "Ctrl+Shift+S", "export": "Ctrl+E",
    "undo": "Ctrl+Z", "redo": "Ctrl+Shift+Z", "find": "Ctrl+F", "replace": "Ctrl+H", "apply": "Ctrl+Return",
    "add": "Ctrl+Return", "newLine": "Ctrl+Shift+Return", "duplicate": "Ctrl+D", "split": "Ctrl+Shift+D", "merge": "Ctrl+J",
    "previous": "Alt+Up", "next": "Alt+Down", "play": "Ctrl+Space", "playLine": "Alt+Space",
    "setStart": "Ctrl+1", "setEnd": "Ctrl+2", "frameBack": "Alt+Left", "frameForward": "Alt+Right",
    "shift": "Ctrl+Shift+T", "copyLines": "Ctrl+Shift+C", "pasteLines": "Ctrl+Shift+V", "deleteLines": "Ctrl+Shift+Backspace",
    "assignCharacter": "Ctrl+`",
    "formatBold": "Ctrl+B", "formatItalic": "Ctrl+I", "formatUnderline": "Ctrl+U",
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
    ROLE_NAMES = ["sourceIndex", "number", "startTime", "endTime", "character", "cueText", "originalText", "translatedText", "noteCount", "proposalCount", "cps", "warning", "issues", "selected", "comment", "portraitUrl"]
    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.visible: list[int] = []
        self.cache = []
        self._row_keys = []
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

    def rebuild(self, incremental=False):
        visible, cache, row_keys = [], [], []
        backend = self.backend
        doc = backend.editor.document
        if doc.cues:
            backend._compute()
        old_rows = {source: (key, row) for source, key, row in zip(self.visible, self._row_keys, self.cache)}
        portraits = {
            card.id: 'image://project/' + portrait['image']
            for card in doc.characters
            for portrait in card.portraits
            if portrait['id'] == card.primary and portrait['image'] in doc.images
        }
        for i, cue in enumerate(doc.cues):
            info = backend._quality_cache[i]
            if not backend.matches(cue, info):
                continue
            visible.append(i)
            notes = backend._review_counts.get((cue.id, 'note'), 0)
            proposals = backend._review_counts.get((cue.id, 'proposal'), 0)
            portrait = portraits.get(cue.character_id, '')
            selected = i in backend.selection
            key = (cue.start, cue.end, cue.character, cue.output_text, cue.original, cue.translation,
                   notes, proposals, info['cps'], info['warning'], tuple(info['messages']), selected, cue.comment, portrait)
            row_keys.append(key)
            old_key, old_row = old_rows.get(i, (None, None))
            if key == old_key and old_row['selected'] == selected:
                cache.append(old_row)
                continue
            cache.append({"sourceIndex": i, "number": i + 1, "startTime": format_time(cue.start), "endTime": format_time(cue.end), "character": cue.character, "cueText": plain_text(cue.output_text).replace("\n", "  ↵  "), "originalText": plain_text(cue.original).replace("\n", "  ↵  "), "translatedText": plain_text(cue.translation or "").replace("\n", "  ↵  "), "noteCount": notes, "proposalCount": proposals, "cps": info["cps"], "warning": info["warning"], "issues": "\n".join(info["messages"]), "selected": selected, "comment": cue.comment, "portraitUrl": portrait})
        old_count = len(self.visible)
        if visible == self.visible or (incremental and visible[:old_count] == self.visible):
            if len(visible) > old_count:
                self.beginInsertRows(QModelIndex(), old_count, len(visible) - 1)
                self.visible.extend(visible[old_count:])
                self.cache.extend(cache[old_count:])
                self.endInsertRows()
            for row in range(old_count):
                if self.cache[row] != cache[row]:
                    self.cache[row] = cache[row]
                    self.dataChanged.emit(self.index(row), self.index(row), [])
        else:
            self.beginResetModel()
            self.visible, self.cache = visible, cache
            self.endResetModel()
        self._row_keys = row_keys

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
    cardsRequested = Signal(str)
    reviewsRequested = Signal()
    cropRequested = Signal()
    captureChanged = Signal()
    documentReplaced = Signal()
    cardSaved = Signal(str)
    transcriptionRequested = Signal()

    @Slot()
    def openTranscription(self):
        if not self.busy:
            self.transcriptionRequested.emit()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.editor = Editor()
        self.media_controller = MediaController(self)
        self.media_controller.error.connect(self.show_error)
        self.media_controller.metadataReady.connect(self._media_metadata)
        self.media_controller.positionChanged.connect(self.playbackChanged)
        self.media_controller.captured.connect(self._frame_captured)
        data_dir = os.environ.get("SUBSTANCE_DATA_DIR") or QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = QSettings(str(self.data_dir / "settings.ini"), QSettings.Format.IniFormat)
        from .appearance import AppearanceSettings
        self._appearance = AppearanceSettings(self.settings, self)
        self.recovery_path = self.data_dir / f"recovery-{os.getpid()}.substance"
        self.path = ""
        self._use_ass_styles = self.settings.value("useAssStyles", False, type=bool)
        self._ass_style_skeleton = None
        self._ass_style_states = {}
        self._ass_highlighters = []
        self._ass_notice = None
        self._ass_formatted = self.settings.value("assFormatted", False, type=bool)
        self._ass_original_formatted = self.settings.value("assOriginalFormatted", self._ass_formatted, type=bool)
        self._preserve_ass_formatting = self.settings.value("preserveAssFormatting", False, type=bool)
        self._card_id = ""
        self._card_draft = {}
        self._capture_image = QImage()
        self._capture_meta = {}
        self._capture_serial = 0
        self._capture_request = None
        self._mode = "timing"
        self._section = "timing"
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
        self._preview = self.editor.document.ass_text(use_ass_styles=self._use_ass_styles)
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
        self._review_defaults = {name: self.settings.value('reviewChecks/' + name, True, type=bool)
                                 for name in ('lineLength', 'readingSpeed', 'lineCount', 'overlaps')}
        self._line_count_limit = self.settings.value('lineCountLimit', 2, type=int)
        self._document_defaults = self.defaultReviewSettings
        self.editor.document.review_settings = dict(self._document_defaults)
        default_shortcuts = {**SHORTCUTS, **({"redo": "Ctrl+Y"} if sys.platform == "win32" else {"play": "Ctrl+Shift+Space"} if sys.platform == "darwin" else {})}
        try:
            self._shortcuts = {**default_shortcuts, **json.loads(self.settings.value("shortcuts", "{}"))}
            if self._shortcuts.get("assignCharacter") in ("Ctrl+?", "Ctrl+Shift+?"):
                self._shortcuts["assignCharacter"] = default_shortcuts["assignCharacter"]
                self.settings.setValue("shortcuts", json.dumps(self._shortcuts))
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
        self.layout_shortcuts = LayoutShortcuts(self)
        self.currentChanged.connect(self._update_ass_styles)
        self.local_repository = LocalDocumentRepository()
        self.online = OnlineController(self)
        from .speech import SpeechController
        self.speech = SpeechController(self)
        from .tools_controller import ToolsController
        self.tools = ToolsController(self)
        from .timing_controller import TimingController
        self.timing = TimingController(self)
        from .portraits_controller import PortraitsController
        self.portraits = PortraitsController(self)
        from .hardsub_controller import HardsubController
        self.hardsub = HardsubController(self)
        from .language_controller import LanguageController
        self.language_assistance = LanguageController(self)
        from .workflow_controllers import TransferController, QualityProfiles
        from .batch_processing import BatchController
        from .frame_index import FrameController
        from .alignment_models import AlignmentModels
        from .bitmap_subtitles import BitmapController
        self.transfer = TransferController(self)
        self.quality_profiles = QualityProfiles(self)
        self.batch_files = BatchController(self)
        self.frames = FrameController(self)
        self.alignment_models = AlignmentModels(self)
        self.bitmap_subtitles = BitmapController(self)

    @Property(QObject, constant=True)
    def fileTransfer(self):
        return self.transfer

    @Property(QObject, constant=True)
    def qualityProfiles(self):
        return self.quality_profiles

    @Property(QObject, constant=True)
    def batchFiles(self):
        return self.batch_files

    @Property(QObject, constant=True)
    def frameIndex(self):
        return self.frames

    @Property(QObject, constant=True)
    def alignmentModels(self):
        return self.alignment_models

    @Property(QObject, constant=True)
    def bitmapSubtitles(self):
        return self.bitmap_subtitles

    @Slot()
    def openTimingProcessor(self):
        self.tools.open('retime')

    @Slot()
    def openScriptTiming(self):
        self.tools.open('forced')

    @Property(QObject, constant=True)
    def languageAssistance(self):
        return self.language_assistance

    @Property(QObject, constant=True)
    def hardsubTools(self):
        return self.hardsub

    @Slot()
    def openHardsub(self):
        self.hardsub.open()

    @Property(QObject, constant=True)
    def portraitTools(self):
        return self.portraits

    @Slot()
    def openAutoPortraits(self):
        self.portraits.open()

    @Property(QObject, constant=True)
    def editorTools(self):
        return self.tools

    @Property(QObject, constant=True)
    def timingTools(self):
        return self.timing

    @Slot()
    def openShift(self):
        self.timing.open('shift')

    @Slot()
    def openPointSync(self):
        self.timing.open('points')

    @Slot()
    def openChecks(self):
        self.tools.open('checks')

    @Slot()
    def openReflow(self):
        self.tools.open('balance')

    @Slot()
    def openAlignment(self):
        self.tools.open('align')

    @Slot()
    def openScenes(self):
        self.tools.open('scenes')

    @Property(QObject, constant=True)
    def transcription(self):
        return self.speech

    def _ass_style_context(self):
        if not self._use_ass_styles:
            return {}, {}
        doc = self.editor.document
        if self._ass_style_skeleton is not doc.skeleton:
            self._ass_style_skeleton = doc.skeleton
            self._ass_style_states = style_states(doc.skeleton)
        name = doc.cues[self._current].ass_fields.get("Style", "Default") if 0 <= self._current < len(doc.cues) else "Default"
        return self._ass_style_states.get(name, self._ass_style_states.get("Default", {})), self._ass_style_states

    def _update_ass_styles(self):
        base, styles = self._ass_style_context()
        for highlighter in self._ass_highlighters:
            highlighter.base = base
            highlighter.styles = styles
            highlighter.rehighlight()

    @Property(bool, notify=preferencesChanged)
    def useAssStyles(self):
        return self._use_ass_styles

    @Slot(bool)
    def setUseAssStyles(self, value):
        if value == self._use_ass_styles or not self.flush():
            return
        self._use_ass_styles = value
        self.settings.setValue("useAssStyles", value)
        self._update_ass_styles()
        self.preferencesChanged.emit()
        self.changed.emit()
        self._preview_timer.start()

    @Slot(str, int, int, result='QVariantMap')
    def assFormattingState(self, text, start, end):
        return selection_state(text, start, end, *self._ass_style_context())

    @Slot(str, int, int, str, result='QVariantMap')
    def applyAssFormat(self, text, start, end, kind):
        if self._busy or not self.flush() or not self.current.get("exists"):
            return {}
        prepared = self.prepareTranslationFormatting(text, start, end, end)
        text, start, end = prepared["text"], prepared["start"], prepared["end"]
        if text != self.current["editText"]:
            self.show_error("Текст реплики изменился; повторите оформление")
            return {}
        try:
            result = toggle_format(text, start, end, kind, *self._ass_style_context())
        except ValueError as exc:
            self.show_error(str(exc))
            return {}
        cue = self.editor.document.cues[self._current]
        key = "translation" if self._mode == "translation" or cue.translation is not None else "text"
        if not self._guard(lambda: self.editor.update(self._current, **{key: result["text"].replace("\n", r"\N")}), current=False):
            return {}
        return result

    @Property(bool, notify=preferencesChanged)
    def assFormatted(self):
        return self._ass_formatted

    @Slot(bool)
    def setAssFormatted(self, value):
        self._ass_formatted = value
        self.settings.setValue("assFormatted", value)
        for highlighter in self._ass_highlighters:
            if not highlighter.original and highlighter.document() is not None:
                highlighter.formatted = value
                highlighter.rehighlight()
        self.preferencesChanged.emit()

    @Property(bool, notify=preferencesChanged)
    def assOriginalFormatted(self):
        return self._ass_original_formatted

    @Slot(bool)
    def setAssOriginalFormatted(self, value):
        self._ass_original_formatted = value
        self.settings.setValue("assOriginalFormatted", value)
        for highlighter in self._ass_highlighters:
            if highlighter.original and highlighter.document() is not None:
                highlighter.formatted = value
                highlighter.rehighlight()
        self.preferencesChanged.emit()

    @Slot(str, int, int, int, result='QVariantMap')
    def prepareTranslationFormatting(self, text, start, end, cursor):
        if self._preserve_ass_formatting and self._mode == "translation" and 0 <= self._current < self.count:
            return inherit_formatting(self.editor.document.cues[self._current].original, text, start, end, cursor)
        return {"text": text, "start": start, "end": end, "cursor": cursor}

    @Property(bool, notify=preferencesChanged)
    def preserveAssFormatting(self):
        return self._preserve_ass_formatting

    @Slot(bool)
    def setPreserveAssFormatting(self, value):
        if not self.flush():
            return
        self._preserve_ass_formatting = value
        self.settings.setValue("preserveAssFormatting", value)
        self.preferencesChanged.emit()

    @Slot(QObject)
    @Slot(QObject, bool)
    def attachAssDocument(self, quick_document, original=False):
        highlighter = AssHighlighter(quick_document.textDocument(), self._ass_original_formatted if original else self._ass_formatted)
        highlighter.original = original
        highlighter.base, highlighter.styles = self._ass_style_context()
        self._ass_highlighters.append(highlighter)
        highlighter.rehighlight()
        quick_document.destroyed.connect(lambda: self._ass_highlighters.remove(highlighter) if highlighter in self._ass_highlighters else None)

    @Property('QVariantList', notify=changed)
    def assTags(self):
        return inventory(c.output_text for c in self.editor.document.cues)

    @Slot('QVariantList', result=bool)
    def removeAssTags(self, names):
        if not names:
            return False
        return self._guard(lambda: remove_document_tags(self.editor, set(names)))

    def _warn_ass(self, path, *, sidecar=False, originals=False):
        if Path(path).suffix.lower() not in (".ass", ".ssa"):
            return
        if self._ass_notice is not None:
            self._ass_notice.close()
        notice = QMessageBox()
        notice.setIcon(QMessageBox.Icon.Warning)
        notice.setWindowTitle("Сохранение ASS")
        notice.setText("ASS содержит только " + ("оригинальный" if originals else "итоговый") + " текст субтитров.")
        detail = "Оригинал и перевод вместе сохраняются только в формате .substance. При повторном открытии одного ASS восстановить обе версии нельзя."
        if sidecar:
            detail += "\n\nДанные оригинала сохранены рядом: " + Path(path).name + ".substance. Не удаляйте этот файл."
        else:
            detail += "\n\nСохраните проект .substance, чтобы сохранить оригинал, перевод и данные проекта."
        notice.setInformativeText(detail)
        notice.setStandardButtons(QMessageBox.StandardButton.Ok)
        self._ass_notice = notice
        # Own the native warning and attach it to the QML application window.
        for window in QGuiApplication.topLevelWindows():
            if window.objectName() == "substanceWindow":
                notice.winId()
                notice.windowHandle().setTransientParent(window)
                break
        notice.open()

    @Property(QObject, constant=True)
    def onlineSession(self):
        return self.online

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
        return self.editor.dirty or bool(self.draft) or bool(self._card_draft)

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def title(self):
        if self.online.active:
            return self.online.context.get("episode_name", "Онлайн-серия")
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

    SECTIONS = (("preparation", "Подготовка"), ("timing", "Тайминг"),
                ("translation", "Перевод"), ("post", "Пост"))

    @Property(str, notify=currentChanged)
    def section(self):
        return self._section

    @Property('QStringList', constant=True)
    def sectionKeys(self):
        return [key for key, _ in self.SECTIONS]

    @Property('QStringList', constant=True)
    def sectionLabels(self):
        return [label for _, label in self.SECTIONS]

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

    @Property(bool, notify=changed)
    def hasDocumentRemarks(self):
        self._compute()
        return self._has_document_remarks

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
            return {"exists": False, "start": 0, "end": 2000, "startTime": "00:00:00.000", "endTime": "00:00:02.000", "original": "", "editText": "", "character": "", "characterId": "", "issues": [], "cps": 0, "comment": False}
        cue = self.editor.document.cues[self._current]
        info = self.cue_quality(self._current)
        text = (cue.translation or "") if self._mode == "translation" else cue.output_text
        text = self.draft.get("translation", self.draft.get("text", text))
        return {"exists": True, "id": cue.id, "number": self._current + 1, "start": cue.start, "end": cue.end, "startTime": self.draft.get("start", format_time(cue.start)), "endTime": self.draft.get("end", format_time(cue.end)), "duration": (cue.end - cue.start) / 1000, "character": self.draft.get("character", cue.character), "original": cue.original.replace(r"\N", "\n"), "editText": text.replace(r"\N", "\n"), "characterId": cue.character_id, "comment": cue.comment, "issues": info["messages"], "cps": info["cps"], "maxLine": info["maxLine"]}

    @Property(str, notify=preferencesChanged)
    def theme(self):
        return self._theme

    @Property(QObject, constant=True)
    def appearance(self):
        return self._appearance

    @Property(str, notify=preferencesChanged)
    def importEncoding(self):
        return self._encoding

    @Property(bool, notify=preferencesChanged)
    def motion(self):
        return self._motion

    @Property(int, notify=changed)
    def cpsLimit(self):
        return self.reviewSettings['cpsLimit']

    @Property(int, notify=changed)
    def lineLimit(self):
        return self.reviewSettings['lineLimit']

    @Property('QVariantMap', notify=preferencesChanged)
    def defaultReviewSettings(self):
        return dict(self._review_defaults, cpsLimit=self._cps_limit, lineLimit=self._line_limit,
                    lineCountLimit=self._line_count_limit)

    @Slot(str, 'QVariant')
    def setDefaultReviewSetting(self, name, value):
        if name in self._review_defaults:
            if not isinstance(value, bool):
                return
            self._review_defaults[name] = value
            self.settings.setValue('reviewChecks/' + name, value)
        elif name in ('cpsLimit', 'lineLimit', 'lineCountLimit'):
            try:
                low, high = {'cpsLimit': (1, 100), 'lineLimit': (10, 200), 'lineCountLimit': (1, 10)}[name]
                value = max(low, min(high, int(value)))
            except (ValueError, TypeError, OverflowError):
                return
            setattr(self, {'cpsLimit': '_cps_limit', 'lineLimit': '_line_limit', 'lineCountLimit': '_line_count_limit'}[name], value)
            self.settings.setValue(name, value)
        else:
            return
        # Defaults affect future documents, never the current warnings or plan.
        self.preferencesChanged.emit()

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
            if self._section in ("preparation", "post"):
                self.setMode(self._mode)
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
        settings = self.reviewSettings
        cps_limit, line_limit, project = self.cpsLimit, self.lineLimit, self.isProject
        key = (id(self.editor.document), self.editor.revision, cps_limit, line_limit, project, tuple(sorted(settings.items())))
        if key == self._computed_key:
            return
        cues = self.editor.document.cues
        self._quality_cache = [quality(c, next_cue=cues[i + 1] if i + 1 < len(cues) else None, cps_limit=cps_limit, line_limit=line_limit, line_count_limit=settings["lineCountLimit"], show_length=settings["lineLength"], show_speed=settings["readingSpeed"], show_lines=settings["lineCount"], show_overlaps=settings["overlaps"]) for i, c in enumerate(cues)]
        self._review_counts = {}
        self._has_document_remarks = False
        cue_ids = {cue.id for cue in cues}
        if self.online.active:
            for entry in self.online.reviews.entries:
                if entry['cue_id'] in cue_ids:
                    self._has_document_remarks = True
                if entry["state"] == "open":
                    review_key = (entry["cue_id"], entry["kind"])
                    self._review_counts[review_key] = self._review_counts.get(review_key, 0) + 1
        elif project:
            for entry in self.editor.document.reviews:
                if any(cue_id in cue_ids for cue_id in entry.cue_ids):
                    self._has_document_remarks = True
                if entry.state == 'open':
                    for cue_id in entry.cue_ids:
                        review_key = (cue_id, entry.kind)
                        self._review_counts[review_key] = self._review_counts.get(review_key, 0) + 1
        self._counts_cache = {"all": len(cues), "warnings": sum(q["warning"] for q in self._quality_cache),
                              "notes": sum(self._review_counts.get((c.id, 'note'), 0) > 0 for c in cues),
                              "proposals": sum(self._review_counts.get((c.id, 'proposal'), 0) > 0 for c in cues),
                              "characters": len(self.editor.document.characters) if project else 0}
        self._characters_cache = sorted({c.character for c in cues if c.character})
        self._computed_key = key

    def cue_quality(self, index):
        self._compute()
        return self._quality_cache[index]

    def matches(self, cue, info):
        if self._filter == 'notes' and not self._review_counts.get((cue.id, 'note')):
            return False
        if self._filter == 'proposals' and not self._review_counts.get((cue.id, 'proposal')):
            return False
        if self._filter == "warnings" and not info["warning"]:
            return False
        if self._character_filter and cue.character != self._character_filter:
            return False
        return not self._pattern or self._pattern.search(cue.original + "\n" + cue.output_text) is not None

    def _refresh(self, current=True):
        if self._filter == 'warnings' and not self.checksEnabled:
            self._filter = 'all'
        self._current = min(self._current, self.count - 1)
        self.selection = {i for i in self.selection if i < self.count}
        self.model.rebuild()
        if hasattr(self, "online") and not self.online.checkpoint():
            self.show_error(self.online.status)
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
        except (ValueError, IndexError, OSError, TypeError, KeyError, StopIteration, re.error) as exc:
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
            if key == "translation" and self._mode == "translation" and self._preserve_ass_formatting:
                value = inherit_formatting(cue.original, value)["text"]
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
            # ASS serialization only reads the document. Overlay the one edited
            # cue without copying source history, portraits, or other cues.
            doc = copy(doc)
            doc.cues = list(doc.cues)
            doc.cues[self._current] = copy(doc.cues[self._current])
            for key, value in self.draft.items():
                if key not in ("start", "end"):
                    setattr(doc.cues[self._current], key, value)
        preview = doc.ass_text(use_ass_styles=self._use_ass_styles)
        if preview != self._preview:
            self._preview = preview
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
        if value in ("timing", "translation"):
            self.setSection(value)

    @Slot(str, result=bool)
    def setSection(self, value):
        if value not in self.sectionKeys or not self.flush():
            return False
        # Tool pages retain the last text-editing mode, including translation
        # semantics, while all four sections share the same document and draft.
        self._section = value
        if value in ("timing", "translation"):
            self._mode = value
        self.currentChanged.emit()
        if value in ("timing", "translation"):
            self.focusEditor.emit()
        return True

    @Slot(str)
    def setFilter(self, value):
        if value == 'characters':
            self.openCharacters('')
            return
        if value not in ('all', 'notes', 'proposals', 'warnings'):
            return
        if value == 'warnings' and not self.checksEnabled:
            value = 'all'
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
        if self.flushCard() and self._guard(self.editor.undo):
            self.notify("Правка отменена")

    @Slot()
    def redo(self):
        if self.flushCard() and self._guard(self.editor.redo):
            self.notify("Правка повторена")

    @Slot(bool)
    def apply(self, next_line=False):
        if not self.flush() or self._current < 0:
            return
        if next_line:
            self.navigate(1)
        else:
            self.notify("Изменения применены")

    @Slot(int, int)
    def setRange(self, start, end):
        self._guard(lambda: self.editor.update(self._current, start=start, end=end))

    @Slot(str)
    def setEdge(self, edge):
        self._guard(lambda: self.editor.update(self._current, **{edge: self.media_controller.framePosition}))

    @Slot(int)
    def stepFrame(self, direction):
        position = self.media_controller.framePosition
        self.media_controller.player.pause()
        self.media_controller.seek(self.frames.step(position, direction))

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
            self.editor.batch(self._indices(all_lines), action, parsed, frame_times=self.frames.times)
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
        payload["reviews"] = []
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
                if self.isProject:
                    existing = {c.id for c in doc.characters}
                    doc.characters.extend(c for c in incoming.characters if c.id not in existing)
                    doc.images.update(incoming.images)
                else:
                    for c in incoming.cues:
                        c.character_id = ''
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
        owner = QGuiApplication.focusWindow()
        dialog = QDialog()
        dialog.setWindowTitle("Горячая клавиша")
        dialog.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)
        dialog.setMinimumWidth(440)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)
        layout.addWidget(QLabel("Нажмите новое сочетание клавиш"))
        edit = QKeySequenceEdit(QKeySequence(self._shortcuts.get(action, "")))
        edit.setMaximumSequenceLength(1)
        layout.addWidget(edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Отмена")
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.winId()
        dialog.windowHandle().setTransientParent(owner)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.setShortcut(action, edit.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    @Slot(str, str)
    def preference(self, name, value):
        if name in ('cpsLimit', 'lineLimit'):
            limit = max(1 if name == 'cpsLimit' else 10, min(100 if name == 'cpsLimit' else 200, int(value)))
            self._guard(lambda: self.editor.transact('Настройки проверок', lambda d: d.review_settings.update({name: limit})))
            return
        if name == "theme" and value in ("system", "light", "dark"):
            self._theme = value
            scheme = Qt.ColorScheme.Unknown if value == "system" else Qt.ColorScheme.Dark if value == "dark" else Qt.ColorScheme.Light
            QGuiApplication.styleHints().setColorScheme(scheme)
        elif name == "motion":
            self._motion = value == "true" and not reduce_motion()
            value = self._motion
        elif name == "importEncoding":
            self._encoding = value
        else:
            return
        self.settings.setValue(name, value)
        self.preferencesChanged.emit()
        self._refresh()

    @Slot(float, str, result=bool)
    @Slot(float, str, 'QVariantMap', result=bool)
    def documentSettings(self, fps, encoding, checks=None):
        import math
        if not math.isfinite(fps) or not 1 <= fps <= 120 or encoding not in ('utf-8', 'cp1251', 'utf-16'):
            self.show_error('Укажите частоту кадров от 1 до 120 и поддерживаемую кодировку')
            return False
        values = dict(self.reviewSettings if checks is None else checks)
        for key in self._review_defaults:
            if not isinstance(values.get(key), bool):
                self.show_error('Некорректные настройки проверок')
                return False
        for key, low, high in [('cpsLimit', 1, 100), ('lineLimit', 10, 200), ('lineCountLimit', 1, 10)]:
            if type(values.get(key)) is not int or not low <= values[key] <= high:
                self.show_error('Некорректный порог проверки')
                return False
        def apply(doc):
            if doc.fps != fps:
                doc.fps = fps
                doc.metadata["fps_source"] = "manual"
            if doc.encoding != encoding:
                doc.encoding, doc.bom = encoding, False
            doc.review_settings.update({key: values[key] for key in self.defaultReviewSettings})
        return self._guard(lambda: self.editor.transact("Настройки документа", apply))

    def _confirm_unsaved(self):
        if self.speech.running:
            self.show_error("Сначала остановите распознавание. Готовые реплики останутся в документе.")
            return False
        if self.online.busy:
            self.show_error("Дождитесь завершения онлайн-запроса")
            return False
        if not self.flushCard() or not self.flush():
            return False
        if self.online.active:
            return self.online.checkpoint()
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
        if hasattr(self, "online"):
            self.online.disconnect()
        self.documentReplaced.emit()
        self._card_draft = {}
        self._document_defaults = self.defaultReviewSettings
        document.review_settings = {**self._document_defaults, **document.review_settings}
        self.editor = Editor(document)
        self.path = path
        self.editor.project_mode = self.isProject
        if self.isProject:
            sync_characters(document)
        self._card_id = ""
        self._capture_request = None
        self._capture_image = QImage()
        self._capture_meta = {}
        self._capture_serial += 1
        self.captureChanged.emit()
        self.draft.clear()
        self._filter, self._search, self._pattern = "all", "", None
        self._character_filter = ""
        self._current = 0 if document.cues else -1
        self.selection = {0} if document.cues else set()
        self._busy = False
        self._message = ""
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
        self._remember_path(path)
        media_path = doc.media.get("path", "")
        if media_path and Path(media_path).is_file():
            self.media_controller.open(media_path)
        else:
            self.media_controller.clear()
        self.notify(f"Открыто реплик: {self.count}" + (f" · Предупреждений импорта: {len(doc.warnings)}" if doc.warnings else ""))
        if doc.warnings:
            QMessageBox.information(None, "Замечания импорта", "\n".join(doc.warnings[:12]))

    def _remember_path(self, path):
        path = str(path)
        self._recents = [path] + [p for p in self._recents if p != path][:9]
        self.settings.setValue("recents", json.dumps(self._recents))

    def _load_error(self, value):
        self._extract_task = None
        self._busy = False
        self.show_error(value)

    @Slot(result=bool)
    def save(self):
        if not self.flushCard() or not self.flush():
            return False
        if self.online.active:
            saved = self.online.checkpoint()
            if saved:
                self.online.sync()
            return saved
        if not self.path:
            return self.saveAs()
        try:
            self.local_repository.save(self.editor.document, self.path, use_ass_styles=self._use_ass_styles)
            self._warn_ass(self.path, sidecar=True)
            self.editor.mark_saved()
            self._remove_recovery()
            self.notify("Сохранено")
            return True
        except (ValueError, OSError) as exc:
            self.show_error("Не удалось сохранить: " + str(exc))
            return False

    @Slot(result=bool)
    def saveAs(self):
        if not self.flushCard() or not self.flush():
            return False
        default = self.path or "Новый проект.substance"
        path, selected = QFileDialog.getSaveFileName(None, "Сохранить как", default, "Проект Substance (*.substance);;ASS (*.ass)")
        if not path:
            return False
        if not Path(path).suffix:
            path += ".substance" if "Substance" in selected else ".ass"
        if self.isProject and Path(path).suffix.lower() != '.substance':
            try:
                export_document(self.editor.document, path, use_ass_styles=self._use_ass_styles)
                self._warn_ass(path)
                self.notify('ASS экспортирован; работа продолжается в проекте')
                return True
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))
                return False
        if self.online.active:
            try:
                export_document(self.editor.document, path, use_ass_styles=self._use_ass_styles)
                self._warn_ass(path)
                self.notify("Автономная копия сохранена; онлайн-серия остаётся открытой")
                return True
            except (ValueError, OSError) as exc:
                self.show_error(str(exc))
                return False
        return self._save_path(path)

    @Slot(bool)
    def exportDialog(self, originals=False):
        if not self.flushCard() or not self.flush():
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
                export_document(self.editor.document, path, originals=originals, use_ass_styles=self._use_ass_styles)
                self._warn_ass(path, originals=originals)
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
        # The static about() helper creates an unowned modeless window on macOS.
        # Give this dialog the same native ownership/lifetime as other dialogs.
        owner = QGuiApplication.focusWindow()
        dialog = QMessageBox()
        dialog.setWindowTitle("О Substance")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"Substance {__version__}")
        dialog.setInformativeText("Редактор ASS для тайминга и перевода.\nPython · Qt Quick · FFmpeg · libass\n\nПредварительная версия.\nГорячие клавиши доступны в меню и настройках.")
        dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
        dialog.winId()
        dialog.windowHandle().setTransientParent(owner)
        dialog.exec()

    @Slot(result=bool)
    def requestClose(self):
        if self.speech.running:
            self.speech.stop()
            self.speech._flush_segments()
            self.speech.detach()
        if self.online.active:
            if not self.flushCard() or not self.flush() or not self.online.checkpoint():
                return False
            return self.online.request_close()
        if self._confirm_unsaved():
            self._remove_recovery()
            return True
        return False

    def confirm_online_close(self, error):
        dialog = QMessageBox()
        dialog.setWindowTitle("Последние правки ещё не на сервере")
        dialog.setText("Полный черновик сохранён на этом компьютере. DubbingManager пока показывает последнюю подтверждённую версию.")
        dialog.setInformativeText(str(error))
        retry = dialog.addButton("Повторить отправку", QMessageBox.ButtonRole.AcceptRole)
        local = dialog.addButton("Закрыть с локальным черновиком", QMessageBox.ButtonRole.ActionRole)
        dialog.addButton("Отмена", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(retry)
        owner = QGuiApplication.focusWindow()
        if owner:
            dialog.winId()
            dialog.windowHandle().setTransientParent(owner)
        dialog.exec()
        if dialog.clickedButton() is retry:
            self.online.retry_close()
        elif dialog.clickedButton() is local:
            self.online.close_locally()
        else:
            self.online.cancel_close()

    def _remove_recovery(self):
        try:
            self.recovery_path.unlink(missing_ok=True)
        except OSError:
            pass

    @Slot()
    def autosave(self):
        if self.online.active:
            if self.flush():
                self.online.checkpoint()
            return
        if not self.dirty:
            return
        data = self.editor.document.to_dict()
        data["recovery_path"] = self.path
        data["recovery_pid"] = os.getpid()
        data["recovery_draft"] = self.draft
        data["recovery_card_draft"] = self._card_draft
        data["recovery_current"] = self._current
        data["recovery_mode"] = self._mode
        data["recovery_section"] = self._section
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
                    self._card_draft = data.get("recovery_card_draft", {})
                    self._card_id = self._card_draft.get("id", "")
                    self._mode = data.get("recovery_mode", "timing")
                    if self._mode not in ("timing", "translation"):
                        self._mode = "timing"
                    self._section = data.get("recovery_section", self._mode)
                    if self._section not in self.sectionKeys:
                        self._section = self._mode
                    media_path = self.editor.document.media.get("path", "")
                    if media_path and Path(media_path).is_file():
                        self.media_controller.open(media_path)
                    self._refresh()
                    self.notify("Работа восстановлена; сохраните документ")
                    if self._card_draft:
                        self.cardsRequested.emit(self._card_id)
                path.unlink(missing_ok=True)
                break
            except (ValueError, OSError, TypeError, KeyError):
                continue

    @Property(bool, notify=changed)
    def isProject(self):
        return bool(getattr(self, 'online', None) and self.online.active) or bool(self.path and Path(self.path).suffix.lower() == '.substance' and not self.path.lower().endswith(('.ass.substance', '.ssa.substance')))

    @Property('QVariantMap', notify=changed)
    def reviewSettings(self):
        return {**self._document_defaults, **self.editor.document.review_settings}

    @Property(bool, notify=changed)
    def checksEnabled(self):
        settings = self.reviewSettings
        return any(settings[name] for name in self._review_defaults)

    def review_count(self, cue_id, kind):
        self._compute()
        return self._review_counts.get((cue_id, kind), 0)

    def _review_view(self, entry):
        result = asdict(entry)
        cues = [(i, c) for i, c in enumerate(self.editor.document.cues) if c.id in entry.cue_ids]
        result.update(archived=not cues, numbers=[i+1 for i, c in cues], current=(getattr(cues[0][1], entry.field) or '') if len(cues) == 1 else '', cueId=cues[0][1].id if len(cues) == 1 else '')
        field_changed = len(cues) == 1 and entry.field == 'text' and cues[0][1].translation is not None
        result['currentField'] = 'translation' if field_changed else entry.field
        if field_changed:
            result['current'] = cues[0][1].translation
        result['stale'] = entry.kind == 'proposal' and (entry.invalidated or field_changed or len(cues) != 1 or result['current'] != entry.base)
        result['caption'] = ('Реплики ' + ', '.join(str(i+1) for i, c in cues)) if cues else 'Удалённая реплика'
        chunks = []
        for op, a, b, c, d in difflib.SequenceMatcher(None, entry.base, entry.replacement, autojunk=False).get_opcodes():
            if op in ('replace', 'delete'):
                chunks.append('<span style="color:#a53636"><s>' + html.escape(entry.base[a:b]) + '</s></span>')
            if op in ('replace', 'insert'):
                chunks.append('<span style="color:#237d46"><u>' + html.escape(entry.replacement[c:d]) + '</u></span>')
            if op == 'equal':
                chunks.append(html.escape(entry.base[a:b]))
        result['diff'] = ''.join(chunks).replace(r'\N', '<br>').replace('\n', '<br>')
        return result

    @Property('QVariantList', notify=changed)
    def cueChoices(self):
        return [{'id': c.id, 'label': f'{i+1} · {c.character} · {plain_text(c.output_text)[:60]}', 'text': c.text.replace(r'\N', '\n'), 'translation': (c.translation or '').replace(r'\N', '\n')} for i, c in enumerate(self.editor.document.cues)]

    @Property('QVariantList', notify=changed)
    def reviewEntries(self):
        return [self._review_view(r) for r in reversed(self.editor.document.reviews)] if self.isProject else []

    @Property('QVariantList', notify=changed)
    def currentReviews(self):
        cue_id = self.current.get('id', '')
        return [r for r in self.reviewEntries if cue_id in r['cue_ids']]

    def _card_view(self, card):
        result = asdict(card)
        result['portraits'] = [{**p, 'url': 'image://project/' + p['image'],
                               'media_path': p.get('media_path', ''),
                               'time': p.get('time', p.get('frame', {}).get('time_ms', 0))}
                              for p in card.portraits]
        primary = next((p for p in card.portraits if p['id'] == card.primary), None)
        result['portraitUrl'] = 'image://project/' + primary['image'] if primary else ''
        result['cues'] = [{'id': c.id, 'number': i+1, 'time': format_time(c.start), 'text': plain_text(c.output_text)} for i, c in enumerate(self.editor.document.cues) if c.character_id == card.id]
        return result

    @Property('QVariantList', notify=changed)
    def characterCards(self):
        return [self._card_view(c) for c in self.editor.document.characters] if self.isProject else []

    @Property(bool, notify=changed)
    def hasCardDraft(self):
        return bool(self._card_draft)

    @Property('QVariantMap', notify=changed)
    def currentCard(self):
        card = next((self._card_view(c) for c in self.editor.document.characters if c.id == self._card_id), {'id': '', 'name': '', 'aliases': [], 'export_name': '', 'description': '', 'speech': '', 'notes': '', 'portraits': [], 'portraitUrl': '', 'cues': []})
        return {**card, **self._card_draft} if self._card_draft and self._card_draft.get('id') == self._card_id else card

    @Property(str, notify=changed)
    def currentPortraitUrl(self):
        card = next((c for c in self.editor.document.characters if c.id == self.current.get('characterId', '')), None)
        return self._card_view(card)['portraitUrl'] if card and self.isProject else ''

    @Property('QVariantMap', notify=captureChanged)
    def captureInfo(self):
        return {**self._capture_meta, 'url': ('image://project/capture?' + str(self._capture_serial)) if not self._capture_image.isNull() else '', 'width': self._capture_image.width(), 'height': self._capture_image.height()}

    def _save_path(self, path):
        try:
            if str(path).lower().endswith(('.ass.substance', '.ssa.substance')):
                raise ValueError('Для самостоятельного проекта выберите имя без .ass.substance или .ssa.substance')
            if Path(path).suffix.lower() == '.substance':
                self.editor.transact('Подготовка проекта', sync_characters)
            save_document(self.editor.document, path, use_ass_styles=self._use_ass_styles)
            self._warn_ass(path, sidecar=True)
            self.path = path
            self.editor.project_mode = self.isProject
            self.editor.mark_saved()
            self._remove_recovery()
            self._remember_path(path)
            self._refresh()
            self.notify('Сохранено')
            return True
        except (ValueError, OSError) as exc:
            self.show_error('Не удалось сохранить: ' + str(exc))
            return False

    @Slot(result=bool)
    def ensureProject(self):
        if self.isProject:
            return self.flush()
        if not self.flush():
            return False
        suggested = Path(self.path) if self.path else Path('Новый проект.substance')
        if str(suggested).lower().endswith(('.ass.substance', '.ssa.substance')):
            suggested = suggested.with_suffix('')
        path, _ = QFileDialog.getSaveFileName(None, 'Сохранить проект для заметок и персонажей', str(suggested.with_suffix('.substance')), 'Проект Substance (*.substance)')
        if not path:
            return False
        if Path(path).suffix.lower() != '.substance':
            path += '.substance'
        return self._save_path(path)

    @Slot(str, bool)
    def setReviewSetting(self, name, value):
        if name not in ('lineLength', 'readingSpeed', 'lineCount', 'overlaps'):
            return
        self._guard(lambda: self.editor.transact('Настройки проверок', lambda d: d.review_settings.update({name: value})))

    @Slot()
    def openReviews(self):
        if self.online.active:
            self.online.reviews.refresh()
        if self.ensureProject():
            self.reviewsRequested.emit()

    @Slot(str)
    def openCharacters(self, card_id=''):
        if self.ensureProject() and self.flushCard():
            self._card_id = card_id or self.current.get('characterId', '')
            self.changed.emit()
            self.cardsRequested.emit(self._card_id)

    @Slot(str)
    def selectCard(self, card_id):
        if self._card_draft and card_id != self._card_id and not self.flushCard():
            return
        self._card_id = card_id
        self.changed.emit()

    @Slot(str, str, str, result=bool)
    def addReview(self, kind, text, replacement):
        if self.online.active:
            return self.online.reviews.create(kind, text, replacement)
        if kind not in ('note', 'proposal') or not self.ensureProject() or self._current < 0:
            return False
        cue = self.editor.document.cues[self._current]
        target = 'translation' if self._mode == 'translation' or cue.translation is not None else 'text'
        return self._guard(lambda: self.editor.add_review(cue.id, text, replacement=replacement.replace('\n', r'\N') if kind == 'proposal' else None, target=target))

    @Slot(str, str, result=bool)
    def editNote(self, entry_id, text):
        return self.isProject and self._guard(lambda: self.editor.edit_note(entry_id, text))

    @Slot(str, str)
    def reviewAction(self, entry_id, action):
        if not self.isProject:
            return
        def edit():
            if action == 'apply':
                self.editor.apply_proposal(entry_id)
            elif action == 'delete':
                self.editor.delete_note(entry_id)
            else:
                self.editor.review_state(entry_id, action)
        self._guard(edit)

    @Slot(str, str, str, str, result=bool)
    def rebaseProposal(self, entry_id, cue_id, replacement, text):
        return self.isProject and self._guard(lambda: self.editor.rebase_proposal(entry_id, cue_id, replacement.replace('\n', r'\N'), text))

    @Slot(str)
    def selectCueId(self, cue_id):
        index = next((i for i, c in enumerate(self.editor.document.cues) if c.id == cue_id), -1)
        if index >= 0 and self.flush():
            self._filter, self._character_filter, self._search, self._pattern = 'all', '', '', None
            self._refresh()
            if self.select(index, 0):
                if self._section in ("preparation", "post"):
                    self.setMode(self._mode)
                self.seekCurrent()

    @Slot(str, str, str, str, str, str, str, result=bool)
    def saveCharacter(self, card_id, name, aliases, export_name, description, speech, notes):
        if not self.ensureProject():
            return False
        def edit():
            self._card_id = self.editor.save_character(card_id, name, aliases.split(','), export_name, description, speech, notes)
            self._card_draft = {}
        ok = self._guard(edit)
        if ok:
            self.cardSaved.emit(self._card_id)
        return ok

    @Slot(str, str, str, str, str, str, str)
    def stageCard(self, card_id, name, aliases, export_name, description, speech, notes):
        if self.isProject:
            self._card_draft = {'id': card_id, 'name': name, 'aliases': aliases.split(','), 'export_name': export_name, 'description': description, 'speech': speech, 'notes': notes}
            self.changed.emit()

    @Slot(result=bool)
    def flushCard(self):
        if not self._card_draft:
            return True
        d = self._card_draft
        return self.saveCharacter(d['id'], d['name'], ','.join(d['aliases']), d['export_name'], d['description'], d['speech'], d['notes'])

    @Slot()
    def discardCardDraft(self):
        self._card_draft = {}
        self.changed.emit()

    @Slot(str)
    def assignCharacter(self, card_id):
        if self.isProject:
            self._guard(lambda: self.editor.assign_character(self._indices(), card_id))

    @Slot(str, result='QVariantList')
    def characterSuggestions(self, prefix):
        prefix = prefix.strip().casefold()
        choices = self.editor.character_choices()
        matches = [c for c in choices if any(v.casefold().startswith(prefix) for v in [c['name'], *c['aliases']])]
        return sorted(matches, key=lambda c: (c['name'].casefold() != prefix,
                                              prefix not in [v.casefold() for v in c['aliases']], c['name'].casefold()))

    @Slot(str, bool, result=bool)
    def assignCharacterName(self, name, create=False):
        if not self._indices():
            return False
        return self._guard(lambda: self.editor.assign_character_name(self._indices(), name, create=create))

    @Slot(str)
    def deleteCharacter(self, card_id):
        if self.isProject and self._guard(lambda: self.editor.delete_character(card_id)):
            self._card_id = ''
            self.changed.emit()

    @Slot(str)
    def capturePortrait(self, card_id):
        if self.ensureProject():
            self._capture_request = (id(self.editor), self.path, card_id)
            self.media_controller.captureFrame()

    def _frame_captured(self, image, time, path):
        request = self._capture_request
        self._capture_request = None
        if request is None or request[:2] != (id(self.editor), self.path) or not self.isProject:
            return
        self._begin_crop(image, {'cardId': request[2], 'media_path': path, 'time': time, 'portraitId': '', 'crop': [0, 0, 1, 1]})

    def _begin_crop(self, image, meta):
        self._capture_image = image
        self._capture_meta = meta
        self._capture_serial += 1
        self.captureChanged.emit()
        self.cropRequested.emit()

    @Slot(str)
    def importPortrait(self, card_id):
        if not self.ensureProject():
            return
        path, _ = QFileDialog.getOpenFileName(None, 'Изображение персонажа', '', 'Изображения (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            try:
                self._begin_crop(load_image(path), {'cardId': card_id, 'media_path': '', 'time': 0, 'portraitId': '', 'crop': [0, 0, 1, 1]})
            except ValueError as exc:
                self.show_error(str(exc))

    @Slot(str, str)
    def recropPortrait(self, card_id, portrait_id):
        if not self.isProject:
            return
        card = next((c for c in self.editor.document.characters if c.id == card_id), None)
        portrait = next((p for p in card.portraits if p['id'] == portrait_id), None) if card else None
        if portrait:
            self._begin_crop(decode_image(self.editor.document.images[portrait['source']]), {**portrait, 'cardId': card_id, 'portraitId': portrait_id, 'primary': card.primary == portrait_id})

    @Slot(str, str, float, float, float, float, bool, result=bool)
    def savePortrait(self, card_id, new_name, x, y, width, height, primary):
        if not self.isProject or self._capture_image.isNull() or not self.flush():
            return False
        try:
            crop = [x, y, width, height]
            cropped = crop_image(self._capture_image, crop)
            source_key = self._capture_meta.get('source', '')
            if source_key in self.editor.document.images:
                source_data = self.editor.document.images[source_key]
            else:
                source_key, source_data = encode_image(self._capture_image, source=True)
            image_key, image_data = encode_image(cropped)
            portrait = {'id': self._capture_meta.get('portraitId') or identity('portrait'), 'source': source_key, 'image': image_key, 'crop': crop, 'media_path': self._capture_meta.get('media_path', ''), 'time': self._capture_meta.get('time', 0), 'make_primary': primary}
            if self.online.active:
                portrait['frame'] = self._capture_meta.get('frame', {})
                portrait['time'] = self._capture_meta.get('time', portrait['frame'].get('time_ms', 0))
                return self.online.glossary_session.save_portrait(
                    card_id, new_name, portrait, {source_key: source_data, image_key: image_data})
            # Character creation and its first portrait form one undoable operation.
            def edit(doc):
                from .project import CharacterCard
                nonlocal card_id
                if not card_id:
                    if not new_name.strip() or any(c.name == new_name.strip() for c in doc.characters):
                        raise ValueError('Введите новое уникальное имя персонажа')
                    card_id = identity('char')
                    doc.characters.append(CharacterCard(card_id, new_name.strip(), export_name=new_name.strip()))
                card = next(c for c in doc.characters if c.id == card_id)
                old = next((i for i, p in enumerate(card.portraits) if p['id'] == portrait['id']), None)
                if old is None:
                    card.portraits.append(portrait)
                else:
                    card.portraits[old] = portrait
                doc.images.update({source_key: source_data, image_key: image_data})
                if primary or not card.primary:
                    card.primary = portrait['id']
                self.editor._prune_images(doc)
            if self._guard(lambda: self.editor.transact('Сохранение портрета', edit)):
                self._card_id = card_id
                self.changed.emit()
                self.cardsRequested.emit(card_id)
                return True
        except (ValueError, OSError) as exc:
            self.show_error(str(exc))
        return False

    @Slot(str, str, str)
    def portraitAction(self, card_id, portrait_id, action):
        if self.online.active:
            self.online.glossary_session.portrait_action(card_id, portrait_id, action)
            return
        if self.isProject:
            self._guard(lambda: self.editor.portrait_action(card_id, portrait_id, action))

    @Slot(str, str)
    def seekPortrait(self, card_id, portrait_id):
        card = next((c for c in self.editor.document.characters if c.id == card_id), None)
        portrait = next((p for p in card.portraits if p['id'] == portrait_id), None) if card else None
        if portrait and portrait.get('media_path'):
            if not Path(portrait['media_path']).is_file():
                self.show_error('Исходное видео недоступно. Изображение сохранено в проекте.')
                return
            if self.media_controller.path != portrait['media_path']:
                self.openMediaPath(portrait['media_path'])
                self.media_controller.seekOnLoad(portrait['time'])
            else:
                self.media_controller.seek(portrait['time'])

    def shutdown(self):
        self.transfer.reset()
        self.batch_files.shutdown()
        self.frames.shutdown()
        self.alignment_models.shutdown()
        self.bitmap_subtitles.shutdown()
        self.language_assistance.shutdown()
        self.hardsub.shutdown()
        self.portraits.shutdown()
        self.tools.shutdown()
        self.speech.shutdown()
        if self._ass_notice is not None:
            self._ass_notice.close()
        self.online.shutdown()
        self.layout_shortcuts.detach()
        for name in ("_spelling_task", "_extract_task"):
            task = getattr(self, name, None)
            if task:
                task.cancel()
        self.settings.sync()
        self.media_controller.shutdown()
        QThreadPool.globalInstance().waitForDone(5000)
