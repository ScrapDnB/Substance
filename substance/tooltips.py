"""OS-owned tooltip regions over the existing Qt content view.

The OS controls appearance, placement and dwell time. No overlay views, event
interception or additional SDK requirements are needed on macOS.
"""
from __future__ import annotations

import ctypes as C
import sys

from PySide6.QtCore import QObject, QEvent, Property, QRectF, Signal, QTimer
from PySide6.QtGui import QGuiApplication, QPlatformSurfaceEvent
from PySide6.QtQml import QmlElement
from PySide6.QtQuick import QQuickItem

QML_IMPORT_NAME = "Substance"
QML_IMPORT_MAJOR_VERSION = 1


def tooltip_rect(item, window):
    """Scene rectangle clipped to the viewport and any clipping ancestors."""
    rect = item.mapRectToScene(QRectF(0, 0, item.width(), item.height()))
    rect = rect.intersected(QRectF(0, 0, window.width(), window.height()))
    ancestor = item.parentItem()
    while ancestor:
        if not ancestor.isVisible():
            return QRectF()
        if ancestor.clip():
            rect = rect.intersected(ancestor.mapRectToScene(
                QRectF(0, 0, ancestor.width(), ancestor.height())))
        ancestor = ancestor.parentItem()
    return rect


class _MacRegion:
    def __init__(self, window):
        import objc
        self.view = objc.objc_object(c_void_p=C.c_void_p(int(window.winId())))
        self.tag = None
        # NSView keeps only a weak reference to the tooltip owner.
        self.owner = None

    def set(self, rect, text):
        from AppKit import NSMakeRect
        from Foundation import NSString
        self.close()
        y = rect.y() if self.view.isFlipped() else self.view.bounds().size.height - rect.bottom()
        self.owner = NSString.stringWithString_(text)
        self.tag = self.view.addToolTipRect_owner_userData_(
            NSMakeRect(rect.x(), y, rect.width(), rect.height()), self.owner, None)

    def close(self):
        if self.tag is not None:
            self.view.removeToolTip_(self.tag)
            self.tag = None
        self.owner = None


class _WindowsHost(QObject):
    """One standard Win32 tooltip control per Qt window, with multiple tools."""
    def __init__(self, window):
        from ctypes import wintypes as W
        super().__init__(window)

        class ToolInfo(C.Structure):
            _fields_ = [('cbSize', W.UINT), ('uFlags', W.UINT), ('hwnd', W.HWND),
                        ('uId', C.c_size_t), ('rect', W.RECT), ('hinst', W.HINSTANCE),
                        ('lpszText', W.LPWSTR), ('lParam', C.c_ssize_t), ('lpReserved', C.c_void_p)]

        class InitControls(C.Structure):
            _fields_ = [('dwSize', W.DWORD), ('dwICC', W.DWORD)]

        self.ToolInfo, self.RECT = ToolInfo, W.RECT
        self.user32 = C.WinDLL('user32', use_last_error=True)
        self.user32.CreateWindowExW.argtypes = [W.DWORD, W.LPCWSTR, W.LPCWSTR, W.DWORD,
            C.c_int, C.c_int, C.c_int, C.c_int, W.HWND, W.HMENU, W.HINSTANCE, C.c_void_p]
        self.user32.CreateWindowExW.restype = W.HWND
        self.user32.SendMessageW.argtypes = [W.HWND, W.UINT, C.c_size_t, C.c_ssize_t]
        self.user32.SendMessageW.restype = C.c_ssize_t
        self.user32.DestroyWindow.argtypes = [W.HWND]
        self.user32.DestroyWindow.restype = W.BOOL
        self.user32.IsWindow.argtypes = [W.HWND]
        self.user32.IsWindow.restype = W.BOOL
        comctl32 = C.WinDLL('comctl32', use_last_error=True)
        comctl32.InitCommonControlsEx.argtypes = [C.POINTER(InitControls)]
        comctl32.InitCommonControlsEx.restype = W.BOOL
        init = InitControls(C.sizeof(InitControls), 0xFF)
        if not comctl32.InitCommonControlsEx(C.byref(init)):
            raise C.WinError(C.get_last_error())
        self.window = window
        self.parent = 0
        self.hwnd = None
        self.generation = 0
        self.next_id = 0
        window.installEventFilter(self)
        window.destroyed.connect(self.close)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.PlatformSurface and event.surfaceEventType() == QPlatformSurfaceEvent.SurfaceEventType.SurfaceAboutToBeDestroyed:
            # QWindow.close() destroys HWNDs while the QML object stays alive.
            # Release before Windows can recycle either native handle.
            self.close()
        return False

    def ensure(self):
        parent = int(self.window.winId())
        if self.hwnd and self.parent == parent and self.user32.IsWindow(self.hwnd):
            return
        self.close()
        self.parent = parent
        self.hwnd = self.user32.CreateWindowExW(8, 'tooltips_class32', None,
            0x80000000 | 3, 0, 0, 0, 0, self.parent, None, None, None)
        if not self.hwnd:
            raise C.WinError(C.get_last_error())
        self.generation += 1
        self.user32.SendMessageW(self.hwnd, 0x400 + 24, 0, round(480 * self.window.devicePixelRatio()))

    def close(self):
        if self.hwnd:
            if self.user32.IsWindow(self.hwnd):
                self.user32.DestroyWindow(self.hwnd)
            self.hwnd = None


class _WindowsRegion:
    def __init__(self, window):
        host = getattr(window, '_substance_tooltip_host', None)
        if host is None:
            host = window._substance_tooltip_host = _WindowsHost(window)
        self.host = host
        host.next_id += 1
        self.identifier = host.next_id
        self.info = self.buffer = None
        self.generation = 0

    def surface_key(self):
        if not self.host.window.isVisible():
            return None
        self.host.ensure()
        return self.host.parent, self.host.hwnd, self.host.generation

    def set(self, rect, text):
        self.close()
        host = self.host
        host.ensure()
        scale = host.window.devicePixelRatio()
        info = host.ToolInfo()
        info.cbSize, info.uFlags = C.sizeof(info), 0x10 | 0x100  # SUBCLASS | TRANSPARENT
        info.hwnd, info.uId = host.parent, self.identifier
        info.rect = host.RECT(round(rect.left() * scale), round(rect.top() * scale),
                              round(rect.right() * scale), round(rect.bottom() * scale))
        self.buffer = C.create_unicode_buffer(text)
        info.lpszText = C.cast(self.buffer, C.c_wchar_p)
        if not host.user32.SendMessageW(host.hwnd, 0x400 + 50, 0, C.addressof(info)):  # ADDTOOLW
            raise C.WinError(C.get_last_error())
        self.info = info
        self.generation = host.generation

    def close(self):
        if self.info is not None and self.host.hwnd and self.generation == self.host.generation:
            self.host.user32.SendMessageW(self.host.hwnd, 0x400 + 51, 0, C.addressof(self.info))  # DELTOOLW
        self.info = self.buffer = None


@QmlElement
class NativeToolTip(QQuickItem):
    """A nonvisual child describing the tooltip of its parent item."""
    textChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ''
        self._window = self._region = self._state = None
        self._geometry_connections = []
        self._sync_timer = QTimer(self)
        self._sync_timer.setSingleShot(True)
        self._sync_timer.timeout.connect(self._sync)
        self.windowChanged.connect(self._attach)
        self.parentChanged.connect(self._watch_geometry)
        self.textChanged.connect(self._request_update)
        self.enabledChanged.connect(self._request_update)
        self.visibleChanged.connect(self._request_update)

    @Property(str, notify=textChanged)
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        if value != self._text:
            self._text = value
            self.textChanged.emit()

    def _request_update(self, *_args):
        if self._window:
            # Qt 6.12 can skip animation frames when only nonvisual items move.
            # Native tooltip geometry still needs updating in that case.
            self._sync_timer.start(0)
            self._window.update()

    def _watch_geometry(self, *_args):
        for item, name, callback in self._geometry_connections:
            try:
                getattr(item, name).disconnect(callback)
            except (RuntimeError, TypeError):
                pass
        self._geometry_connections = []
        if self._region:
            item = self.parentItem()
            while item:
                for name in ('xChanged', 'yChanged', 'widthChanged', 'heightChanged',
                             'scaleChanged', 'rotationChanged', 'transformOriginChanged',
                             'clipChanged', 'visibleChanged', 'enabledChanged', 'parentChanged'):
                    callback = self._watch_geometry if name == 'parentChanged' else self._request_update
                    getattr(item, name).connect(callback)
                    self._geometry_connections.append((item, name, callback))
                item = item.parentItem()
        self._request_update()

    def _attach(self, window):
        if self._window and self._region:
            self._window.afterAnimating.disconnect(self._sync)
        if self._region:
            self.destroyed.disconnect(self._region.close)
            self._region.close()
        self._window, self._region, self._state = window, None, None
        # Headless checks have no OS window. Linux is outside the supported UI targets.
        platform = QGuiApplication.platformName()
        if window and platform in ('cocoa', 'windows'):
            self._region = _MacRegion(window) if sys.platform == 'darwin' else _WindowsRegion(window)
            self.destroyed.connect(self._region.close)
            window.afterAnimating.connect(self._sync)
        self._watch_geometry()

    def _sync(self):
        if not self._region or not self._window:
            return
        # afterAnimating runs on the GUI thread. It follows layouts, scrolling,
        # resizing and animations without moving any Qt view or handling input.
        item = self.parentItem()
        rect = tooltip_rect(item, self._window) if item and self.isVisible() and self.isEnabled() and self._text else QRectF()
        surface_key = getattr(self._region, 'surface_key', None)
        surface = surface_key() if surface_key else None
        if surface_key and surface is None:
            rect = QRectF()
        state = (rect.x(), rect.y(), rect.width(), rect.height(), self._text,
                 self._window.devicePixelRatio(), surface) if not rect.isEmpty() else None
        if state == self._state:
            return
        if state:
            self._region.set(rect, self._text)
        else:
            self._region.close()
        self._state = state
