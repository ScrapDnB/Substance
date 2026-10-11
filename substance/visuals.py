"""Native scene-graph items for ASS preview and audio timing."""
from __future__ import annotations
import ctypes as C
from ctypes.util import find_library
from pathlib import Path
import os
import sys

import numpy as np
from PySide6.QtCore import QObject, Property, QRectF, Qt, Signal, Slot
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QFont
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickPaintedItem
from . import tooltips  # Register native tooltip descriptions in Substance 1.0.
from . import sidebar  # Register the AppKit navigation layout slot.

QML_IMPORT_NAME = "Substance"
QML_IMPORT_MAJOR_VERSION = 1


class AssImage(C.Structure):
    pass


AssImage._fields_ = [("w", C.c_int), ("h", C.c_int), ("stride", C.c_int), ("bitmap", C.POINTER(C.c_ubyte)), ("color", C.c_uint32), ("dst_x", C.c_int), ("dst_y", C.c_int), ("next", C.POINTER(AssImage)), ("type", C.c_int)]


def libass_path():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
    candidates = [os.environ.get("SUBSTANCE_LIBASS"), str(base / "libass.9.dylib"), str(base / "libass.dll"), str(base / "libass-9.dll"), find_library("ass"), "/opt/homebrew/lib/libass.9.dylib", "/usr/local/lib/libass.9.dylib"]
    return next((p for p in candidates if p and (Path(p).is_file() or p == find_library("ass"))), None)


class AssRenderer:
    def __init__(self):
        path = libass_path()
        if not path:
            raise OSError("Для точного предпросмотра ASS требуется libass")
        self.lib = C.CDLL(path)
        signatures = {
            "ass_library_init": (C.c_void_p, []),
            "ass_library_done": (None, [C.c_void_p]),
            "ass_renderer_init": (C.c_void_p, [C.c_void_p]),
            "ass_renderer_done": (None, [C.c_void_p]),
            "ass_set_extract_fonts": (None, [C.c_void_p, C.c_int]),
            "ass_set_frame_size": (None, [C.c_void_p, C.c_int, C.c_int]),
            "ass_set_storage_size": (None, [C.c_void_p, C.c_int, C.c_int]),
            "ass_set_fonts": (None, [C.c_void_p, C.c_char_p, C.c_char_p, C.c_int, C.c_char_p, C.c_int]),
            "ass_read_memory": (C.c_void_p, [C.c_void_p, C.c_char_p, C.c_size_t, C.c_char_p]),
            "ass_free_track": (None, [C.c_void_p]),
            "ass_render_frame": (C.POINTER(AssImage), [C.c_void_p, C.c_void_p, C.c_longlong, C.POINTER(C.c_int)]),
            "ass_set_fonts_dir": (None, [C.c_void_p, C.c_char_p]),
        }
        for name, (result, args) in signatures.items():
            func = getattr(self.lib, name)
            func.restype, func.argtypes = result, args
        self.library = self.lib.ass_library_init()
        self.lib.ass_set_extract_fonts(self.library, 1)
        self.renderer = self.lib.ass_renderer_init(self.library)
        self.lib.ass_set_fonts(self.renderer, None, b"Arial", 1, None, 1)
        self.track = None
        self.size = (0, 0)
        self.script = ""

    def set_script(self, value):
        if self.script == value:
            return
        self.script = value
        if self.track:
            self.lib.ass_free_track(self.track)
        content = value.encode("utf-8")
        self.track = self.lib.ass_read_memory(self.library, content, len(content), None)

    def render(self, painter, width, height, timestamp, storage_width=1920, storage_height=1080):
        if not self.track or width <= 0 or height <= 0:
            return
        if self.size != (width, height, storage_width, storage_height):
            self.size = width, height, storage_width, storage_height
            self.lib.ass_set_frame_size(self.renderer, width, height)
            # Storage size is video resolution, not the subtitle script's PlayRes.
            self.lib.ass_set_storage_size(self.renderer, storage_width, storage_height)
        changed = C.c_int()
        images = self.lib.ass_render_frame(self.renderer, self.track, timestamp, C.byref(changed))
        while images:
            part = images.contents
            if part.w > 0 and part.h > 0:
                length = part.stride * (part.h - 1) + part.w
                # Last row is not padded in libass; never read beyond the guaranteed size.
                raw = np.ctypeslib.as_array(part.bitmap, shape=(length,))
                alpha = np.zeros((part.h, part.w), dtype=np.uint8)
                for row in range(part.h):
                    alpha[row] = raw[row * part.stride:row * part.stride + part.w]
                rgba = np.empty((part.h, part.w, 4), dtype=np.uint8)
                rgba[:, :, 0] = (part.color >> 24) & 255
                rgba[:, :, 1] = (part.color >> 16) & 255
                rgba[:, :, 2] = (part.color >> 8) & 255
                rgba[:, :, 3] = (alpha.astype(np.uint16) * (255 - (part.color & 255)) // 255).astype(np.uint8)
                image = QImage(rgba.data, part.w, part.h, part.w * 4, QImage.Format.Format_RGBA8888)
                painter.drawImage(part.dst_x, part.dst_y, image)
            images = part.next

    def close(self):
        if self.track:
            self.lib.ass_free_track(self.track)
            self.track = None
        if self.renderer:
            self.lib.ass_renderer_done(self.renderer)
            self.renderer = None
        if self.library:
            self.lib.ass_library_done(self.library)
            self.library = None


@QmlElement
class AssOverlay(QQuickPaintedItem):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._script, self._timestamp = "", 0
        self._video_width, self._video_height = 1920, 1080
        try:
            self.renderer = AssRenderer()
        except OSError:
            self.renderer = None
        self.setAntialiasing(True)

    @Property(bool, constant=True)
    def available(self):
        return self.renderer is not None

    def get_script(self):
        return self._script

    def set_script(self, value):
        self._script = value
        if self.renderer:
            self.renderer.set_script(value)
        self.update()
        self.changed.emit()

    script = Property(str, get_script, set_script, notify=changed)

    def get_timestamp(self):
        return self._timestamp

    def set_timestamp(self, value):
        self._timestamp = value
        self.update()

    timestamp = Property(int, get_timestamp, set_timestamp, notify=changed)

    def get_video_width(self):
        return self._video_width

    def set_video_width(self, value):
        self._video_width = value
        self.update()

    def get_video_height(self):
        return self._video_height

    def set_video_height(self, value):
        self._video_height = value
        self.update()

    videoWidth = Property(int, get_video_width, set_video_width, notify=changed)
    videoHeight = Property(int, get_video_height, set_video_height, notify=changed)

    def paint(self, painter):
        if self.renderer:
            self.renderer.render(painter, round(self.width()), round(self.height()), self._timestamp, self._video_width, self._video_height)

    def __del__(self):
        if getattr(self, "renderer", None):
            self.renderer.close()


@QmlElement
class Waveform(QQuickPaintedItem):
    changed = Signal()
    paletteColorsChanged = Signal()
    seekRequested = Signal(int)
    rangeRequested = Signal(int, int)
    viewChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._media = None
        self._start, self._end, self._view, self._span = 0, 2000, 0, 10000
        self._dark, self._spectral, self._snap = False, False, True
        self._drag = ""
        self._anchor = 0
        self._neighbors = []
        self._palette_colors = {}
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton | Qt.MouseButton.RightButton)
        self.setAcceptHoverEvents(True)
        self.setAntialiasing(True)

    def get_media(self):
        return self._media

    def set_media(self, value):
        self._media = value
        if value:
            value.analysisChanged.connect(self.update)
            value.positionChanged.connect(self.update)
        self.update()

    media = Property(QObject, get_media, set_media, notify=changed)

    def scalar(name, typ, signal):
        def getter(self):
            return getattr(self, "_" + name)
        def setter(self, value):
            setattr(self, "_" + name, value)
            self.update()
            self.changed.emit()
        return Property(typ, getter, setter, notify=signal)

    start = scalar("start", int, changed)
    end = scalar("end", int, changed)
    dark = scalar("dark", bool, changed)
    spectral = scalar("spectral", bool, changed)
    snap = scalar("snap", bool, changed)
    span = scalar("span", int, changed)

    @Property(int, notify=viewChanged)
    def viewStart(self):
        return self._view

    def get_neighbors(self):
        return self._neighbors

    def set_neighbors(self, value):
        self._neighbors = value
        self.update()

    neighbors = Property('QVariantList', get_neighbors, set_neighbors, notify=changed)

    @Property('QVariantMap', notify=paletteColorsChanged)
    def paletteColors(self):
        return self._palette_colors

    @paletteColors.setter
    def paletteColors(self, value):
        self._palette_colors = {key: QColor(value[key]) for key in ('surface', 'border', 'text', 'muted', 'accent', 'warning') if key in value}
        self.paletteColorsChanged.emit()
        self.update()

    def _x(self, ms):
        return (ms - self._view) * self.width() / max(1, self._span)

    def _time(self, x):
        ms = max(0, round(self._view + x / max(1, self.width()) * self._span))
        if self._snap and self._media:
            candidates = list(self._neighbors) + self._media.keyframes
            closest = min(candidates, key=lambda t: abs(t - ms), default=ms)
            if abs(closest - ms) < self._span * 8 / max(1, self.width()):
                return closest
        return ms

    @Slot()
    def center(self):
        self._view = max(0, round((self._start + self._end - self._span) / 2))
        self.viewChanged.emit()
        self.update()

    @Slot(float)
    def zoom(self, factor):
        middle = self._view + self._span / 2
        self._span = int(max(1000, min(300000, self._span * factor)))
        self._view = max(0, int(middle - self._span / 2))
        self.viewChanged.emit()
        self.update()

    def paint(self, painter: QPainter):
        w, h = round(self.width()), round(self.height())
        if w <= 0 or h <= 0:
            return
        colors = self._palette_colors
        background = QColor(colors.get('surface', QColor("#1e1e1e" if self._dark else "#ffffff")))
        grid = QColor(colors.get('border', QColor("#444444" if self._dark else "#dddddd")))
        waveform = QColor(colors.get('text', QColor("#ffffff" if self._dark else "#000000")))
        waveform.setAlpha(170)
        muted = QColor(colors.get('muted', QColor("#999999" if self._dark else "#666666")))
        accent = QColor(colors.get('accent', QColor("#0a84ff")))
        painter.fillRect(0, 0, w, h, background)
        painter.setFont(QFont("Menlo" if sys.platform == "darwin" else "Consolas", 9))
        body_top, body_bottom = 28, h - 12
        if self._media and len(self._media.peaks):
            if self._spectral and len(self._media.spectrum):
                spectrum = self._media.spectrum
                begin = int(self._view / 10)
                count = max(1, int(self._span / 10))
                selected = spectrum[max(0, begin):min(len(spectrum), begin + count)]
                if len(selected):
                    indices = np.minimum(len(selected) - 1, np.linspace(0, len(selected) - 1, w).astype(int))
                    values = selected[indices].T[::-1].astype(np.float32) / 255
                    rgb = np.zeros((64, w, 3), dtype=np.uint8)
                    rgb[:, :, 0] = np.clip(values * 320 - 90, 0, 255)
                    rgb[:, :, 1] = np.clip(values * 280 - 25, 0, 255)
                    rgb[:, :, 2] = np.clip(30 + values * 180, 0, 255)
                    picture = QImage(rgb.data, w, 64, w * 3, QImage.Format.Format_RGB888)
                    occupied = min(w, round(len(selected) / count * w))
                    painter.drawImage(QRectF(0, body_top, occupied, body_bottom - body_top), picture)
            else:
                painter.setPen(QPen(waveform, 1))
                peaks = self._media.peaks
                mid = (body_top + body_bottom) / 2
                amp = (body_bottom - body_top) / 2 - 3
                for x in range(w):
                    begin = int((self._view + x * self._span / w) / 10)
                    end = max(begin + 1, int((self._view + (x + 1) * self._span / w) / 10))
                    if 0 <= begin < len(peaks):
                        value = min(1, float(np.max(peaks[begin:min(len(peaks), end)])))
                        painter.drawLine(x, round(mid - value * amp), x, round(mid + value * amp))
        selection = QColor(accent)
        selection.setAlpha(55)
        painter.fillRect(QRectF(self._x(self._start), body_top, self._x(self._end) - self._x(self._start), body_bottom - body_top), selection)
        painter.setPen(QPen(grid, 1))
        step = next((s for s in (100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000) if s * w / self._span >= 65), 60000)
        first = self._view // step * step
        for ms in range(first, self._view + self._span + step, step):
            x = round(self._x(ms))
            painter.drawLine(x, 24, x, body_bottom)
            seconds = ms // 1000
            label = f"{seconds // 60:02}:{seconds % 60:02}" + (f".{ms % 1000:03}" if step < 1000 else "")
            painter.setPen(muted)
            painter.drawText(x + 4, 17, label)
            painter.setPen(QPen(grid, 1))
        painter.setPen(QPen(QColor(colors.get('warning', QColor("#ffb24c"))), 2))
        if self._media:
            for ms in self._media.keyframes:
                if self._view <= ms <= self._view + self._span:
                    x = round(self._x(ms))
                    painter.drawLine(x, 23, x, 30)
        painter.setPen(QPen(muted, 1, Qt.PenStyle.DashLine))
        for ms in self._neighbors:
            x = round(self._x(ms))
            painter.drawLine(x, body_top, x, body_bottom)
        painter.setPen(QPen(accent, 3))
        for ms in (self._start, self._end):
            x = round(self._x(ms))
            painter.drawLine(x, body_top, x, body_bottom)
            painter.fillRect(QRectF(x - 4, body_top, 8, 16), accent)
        if self._media:
            painter.setPen(QPen(QColor("#ff5a58"), 2))
            x = round(self._x(self._media.position))
            painter.drawLine(x, 20, x, h)

    def mousePressEvent(self, event):
        x = event.position().x()
        self._anchor = self._time(x)
        if event.button() == Qt.MouseButton.RightButton:
            self._drag = "pan"
            self._anchor = int(x)
        elif abs(x - self._x(self._start)) <= 10:
            self._drag = "start"
        elif abs(x - self._x(self._end)) <= 10:
            self._drag = "end"
        elif event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            self._drag = "range"
        else:
            self._drag = "seek"
            self.seekRequested.emit(self._anchor)
        event.accept()

    def mouseMoveEvent(self, event):
        ms = self._time(event.position().x())
        if self._drag == "start":
            self._start = min(self._end - 10, ms)
        elif self._drag == "end":
            self._end = max(self._start + 10, ms)
        elif self._drag == "range":
            self._start, self._end = min(self._anchor, ms), max(self._anchor + 10, ms)
        elif self._drag == "seek":
            self.seekRequested.emit(ms)
        elif self._drag == "pan":
            x = int(event.position().x())
            self._view = max(0, self._view - round((x - self._anchor) * self._span / max(1, self.width())))
            self._anchor = x
            self.viewChanged.emit()
        self.update()

    def mouseReleaseEvent(self, event):
        if self._drag in ("start", "end", "range"):
            self.rangeRequested.emit(self._start, self._end)
        self._drag = ""
        event.accept()

    def wheelEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom(0.8 if event.angleDelta().y() > 0 else 1.25)
        else:
            self._view = max(0, self._view - round(event.angleDelta().y() / 120 * self._span / 8))
            self.viewChanged.emit()
            self.update()
        event.accept()
