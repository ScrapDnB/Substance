"""Device-local editor appearance; never serialized into a subtitle document."""
from __future__ import annotations

import json
import math
import sys
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot
from PySide6.QtGui import QColor, QFontDatabase, QGuiApplication


TIMECODE_FONTS = (
    ("modern", "Menlo" if sys.platform == "darwin" else "Consolas", "перечёркнутый ноль"),
    ("classic", "Verdana", "обычный ноль"),
    ("plain", "Courier New", "обычный ноль"),
    ("chakra", "Chakra Petch", ""),
    ("system", "", "как у текста"),
)


@lru_cache(maxsize=1)
def register_timecode_font():
    """Register the same bundled Bold face used by Dubbing Manager's timer."""
    path = Path(__file__).parent / "resources/fonts/ChakraPetch-Bold.ttf"
    font_id = QFontDatabase.addApplicationFont(str(path))
    families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
    return families[0] if families else ""


DEFAULTS = {
    "general": {
        "uiScale": 100, "tableFont": 12, "editorFont": 16, "originalFont": 14,
        "textFamily": "", "timecodeFont": "modern", "timecodeSize": 12, "rowHeight": 35, "wrapRows": False,
        "stripedRows": True, "rowLines": True, "sidebarWidth": 220, "sidebarVisible": True,
        "accentColor": "", "selectionColor": "", "waveColor": "",
    },
    "lightColors": {"editorBackground": "", "editorText": ""},
    "darkColors": {"editorBackground": "", "editorText": ""},
    "audio": {"waveGain": 100, "spectralContrast": 100},
    "timing": {
        "videoSide": "left", "videoVisible": True, "videoPercent": 47,
        "topPercent": 46, "audioVisible": True, "audioPosition": "middle",
        "audioHeight": 192,
    },
    "translation": {
        "videoSide": "right", "videoVisible": True, "videoPercent": 35,
        "audioVisible": True, "audioHeight": 192, "tableFirst": True,
        "editorHeight": 395, "contextVisible": True, "contextHeight": 300, "originalBelow": False,
    },
}
BOUNDS = {
    "uiScale": (85, 125), "tableFont": (10, 22), "editorFont": (12, 30),
    "originalFont": (10, 26), "rowHeight": (28, 76), "sidebarWidth": (180, 340),
    "videoPercent": (25, 60), "topPercent": (32, 65),
    "audioHeight": (145, 350), "editorHeight": (315, 650),
    "waveGain": (25, 800), "spectralContrast": (25, 300),
    "timecodeSize": (10, 28),
    "contextHeight": (140, 650),
}
OPTIONS = {
    "videoSide": ("left", "right"), "audioPosition": ("middle", "bottom"),
    "timecodeFont": tuple(item[0] for item in TIMECODE_FONTS),
}


def validated(group, name, value):
    default = DEFAULTS[group][name]
    if isinstance(default, bool):
        return value if isinstance(value, bool) else default
    if name in BOUNDS:
        if isinstance(value, bool):
            return default
        try:
            number = float(value)
            if not math.isfinite(number):
                return default
            low, high = BOUNDS[name]
            return max(low, min(high, round(number)))
        except (ValueError, TypeError, OverflowError):
            return default
    if name in OPTIONS:
        return value if value in OPTIONS[name] else default
    if "Color" in name or group.endswith("Colors"):
        if isinstance(value, str) and QColor(value).isValid():
            color = QColor(value)
            # Opaque colors ensure that selection/text remain legible.
            return color.name()
        return ""
    return value[:160] if isinstance(value, str) else default


class AppearanceSettings(QObject):
    changed = Signal()
    columnsChanged = Signal()
    STORAGE_KEY = "appearance.v1"
    COLUMN_BOUNDS = {'number': 32, 'start': 66, 'end': 66, 'portrait': 32, 'actor': 56,
                     'text': 100, 'original': 100, 'translation': 100, 'remarks': 44}

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self._chakra_family = register_timecode_font()
        try:
            saved = json.loads(settings.value(self.STORAGE_KEY, "{}"))
        except (ValueError, TypeError):
            saved = {}
        if not isinstance(saved, dict):
            saved = {}
        self._groups = {}
        for group, defaults in DEFAULTS.items():
            source = saved.get(group, {})
            if not isinstance(source, dict):
                source = {}
            self._groups[group] = {
                name: validated(group, name, source.get(name, default))
                for name, default in defaults.items()
            }
        try:
            columns = json.loads(settings.value('tableColumns.v1', '{}'))
        except (ValueError, TypeError):
            columns = {}
        self._columns = {mode: {} for mode in ('timing', 'translation')}
        if isinstance(columns, dict):
            for mode, values in self._columns.items():
                source = columns.get(mode, {})
                if isinstance(source, dict):
                    for key, value in source.items():
                        if key in self.COLUMN_BOUNDS and type(value) in (int, float) and math.isfinite(value):
                            values[key] = max(self.COLUMN_BOUNDS[key], min(1600, round(value)))
        try:
            visibility = json.loads(settings.value('tableColumns.visibility.v1', '{}'))
        except (ValueError, TypeError):
            visibility = {}
        self._column_visibility = {mode: {} for mode in ('timing', 'translation')}
        if isinstance(visibility, dict):
            for mode, values in self._column_visibility.items():
                source = visibility.get(mode, {})
                if isinstance(source, dict):
                    values.update({key: value for key, value in source.items()
                                   if key in self.COLUMN_BOUNDS and isinstance(value, bool)})

    @Property('QVariantMap', notify=columnsChanged)
    def columnVisibility(self):
        return {mode: dict(values) for mode, values in self._column_visibility.items()}

    @Slot(str, str, bool)
    def setColumnVisible(self, mode, key, visible):
        if mode not in self._column_visibility or key not in self.COLUMN_BOUNDS:
            return
        if self._column_visibility[mode].get(key) != visible:
            self._column_visibility[mode][key] = visible
            self.settings.setValue('tableColumns.visibility.v1', json.dumps(self._column_visibility))
            self.columnsChanged.emit()

    @Slot(str)
    def showAllColumns(self, mode):
        if mode in self._column_visibility:
            self._column_visibility[mode] = dict.fromkeys(self.COLUMN_BOUNDS, True)
            self.settings.setValue('tableColumns.visibility.v1', json.dumps(self._column_visibility))
            self.columnsChanged.emit()

    @Property('QVariantMap', notify=columnsChanged)
    def columnWidths(self):
        return {mode: dict(values) for mode, values in self._columns.items()}

    @Slot(str, str, float)
    def setColumnWidth(self, mode, key, width):
        if mode not in self._columns or key not in self.COLUMN_BOUNDS or not math.isfinite(width):
            return
        width = max(self.COLUMN_BOUNDS[key], min(1600, round(width)))
        if self._columns[mode].get(key) != width:
            self._columns[mode][key] = width
            self.settings.setValue('tableColumns.v1', json.dumps(self._columns))
            self.columnsChanged.emit()

    @Slot(str, str)
    def resetColumnWidth(self, mode, key):
        if mode in self._columns and key in self._columns[mode]:
            del self._columns[mode][key]
            self.settings.setValue('tableColumns.v1', json.dumps(self._columns))
            self.columnsChanged.emit()

    @Property("QVariantMap", notify=changed)
    def general(self):
        return dict(self._groups["general"])

    @Property(str, notify=changed)
    def timecodeFamily(self):
        if self._groups["general"]["timecodeFont"] == "system":
            return self._groups["general"]["textFamily"] or QGuiApplication.font().family()
        if self._groups["general"]["timecodeFont"] == "chakra":
            return self._chakra_family or TIMECODE_FONTS[0][1]
        return next(family for key, family, _ in TIMECODE_FONTS
                    if key == self._groups["general"]["timecodeFont"])

    @Property(bool, notify=changed)
    def timecodeBold(self):
        return self._groups["general"]["timecodeFont"] == "chakra" and bool(self._chakra_family)

    @Property("QVariantList", notify=changed)
    def timecodeOptions(self):
        return [{"value": key,
                 "family": (self._groups["general"]["textFamily"] or QGuiApplication.font().family()) if key == "system" else family,
                 "label": "Системный · как у текста" if key == "system" else f"{family} · {zero}" if zero else f"{family} Bold"}
                for key, family, zero in TIMECODE_FONTS]

    @Property("QVariantMap", notify=changed)
    def timing(self):
        return dict(self._groups["timing"])

    @Property("QVariantMap", notify=changed)
    def translation(self):
        return dict(self._groups["translation"])

    @Property("QVariantMap", notify=changed)
    def lightColors(self):
        return dict(self._groups["lightColors"])

    @Property("QVariantMap", notify=changed)
    def darkColors(self):
        return dict(self._groups["darkColors"])

    @Property("QVariantMap", notify=changed)
    def audio(self):
        return dict(self._groups["audio"])

    def _save(self):
        self.settings.setValue(self.STORAGE_KEY, json.dumps(self._groups, ensure_ascii=False))
        self.changed.emit()

    @Slot(str, str, "QVariant")
    def setValue(self, group, name, value):
        if group not in DEFAULTS or name not in DEFAULTS[group]:
            return
        value = validated(group, name, value)
        if self._groups[group][name] != value:
            self._groups[group][name] = value
            self._save()

    @Slot(str, "QVariantMap")
    def resizeLayout(self, group, values):
        if group not in ("timing", "translation"):
            return
        changed = False
        for name, value in values.items():
            if name in DEFAULTS[group] and name in BOUNDS:
                value = validated(group, name, value)
                changed |= self._groups[group][name] != value
                self._groups[group][name] = value
        if changed:
            self._save()

    @Slot(str)
    def reset(self, group):
        if group in DEFAULTS:
            self._groups[group] = dict(DEFAULTS[group])
            self._save()

    @Slot()
    def resetSizes(self):
        self._groups["general"].update({
            name: value for name, value in DEFAULTS["general"].items()
            if not name.endswith("Color") and name != "sidebarVisible"
        })
        self._save()

    @Slot(str)
    def preset(self, name):
        colors = {
            "system": ("", "", ""),
            "blue": ("#3478f6", "#3478f6", "#508bd4"),
            "mint": ("#258575", "#258575", "#45a48b"),
            "amber": ("#a76519", "#a76519", "#ce943e"),
            "violet": ("#7956c9", "#7956c9", "#9c7ada"),
        }.get(name)
        if colors is None:
            return
        self._groups["general"].update(zip(("accentColor", "selectionColor", "waveColor"), colors))
        self._save()
