"""Cross-platform native-styled desktop entry point."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import json

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, QEvent, Signal
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
import shiboken6

from . import __version__
from .backend import Backend
from . import visuals  # Registers the Substance QML module.
from .macos import MacOSIntegration


class DesktopApplication(QApplication):
    fileRequested = Signal(str)

    def __init__(self, argv):
        self.pending_files = []
        self.accept_files = False
        super().__init__(argv)

    def event(self, event):
        if event.type() == QEvent.Type.FileOpen:
            path = event.file()
            if not path or Path(path).suffix.lower() not in ('.ass', '.ssa', '.srt', '.vtt', '.txt', '.substance'):
                return True
            if self.accept_files:
                self.fileRequested.emit(path)
            else:
                self.pending_files.append(path)
            return True
        return super().event(event)


def main():
    parser = argparse.ArgumentParser(description="Substance ASS subtitle editor")
    parser.add_argument("file", nargs="?", help="ASS, SRT, VTT, TXT or .substance")
    parser.add_argument("--smoke-test", action="store_true", help="Load the QML engine and quit")
    parser.add_argument("--screenshot", help="Save an application-rendered screenshot and quit")
    parser.add_argument("--translation", action="store_true")
    parser.add_argument("--media", help="Video or audio to connect")
    parser.add_argument("--select", type=int, default=1, help="Select a subtitle line (one-based)")
    parser.add_argument("--seek", type=int, default=0, help="Initial media position in milliseconds")
    parser.add_argument("--diagnostics", help="Write runtime diagnostics before exiting")
    args = parser.parse_args()
    app = DesktopApplication([sys.argv[0]])
    app.setApplicationName("Substance")
    app.setOrganizationName("ScrapDnB")
    app.setApplicationVersion(__version__)
    QQuickStyle.setStyle(os.environ.get("SUBSTANCE_STYLE", "macOS" if sys.platform == "darwin" else "FluentWinUI3" if sys.platform == "win32" else "Fusion"))
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "icon.svg")))
    backend = Backend()
    chrome = MacOSIntegration(backend, app)
    scheme = Qt.ColorScheme.Dark if backend.theme == "dark" else Qt.ColorScheme.Light if backend.theme == "light" else Qt.ColorScheme.Unknown
    app.styleHints().setColorScheme(scheme)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.setInitialProperties({"macOSIntegration": chrome, "startupChromeReady": False})
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        backend.shutdown()
        return 1
    window = engine.rootObjects()[0]
    chrome.configure(window)
    app.fileRequested.connect(backend.openPath)
    app.accept_files = True
    for pending_file in app.pending_files:
        QTimer.singleShot(0, lambda path=pending_file: backend.openPath(path))
    if args.translation:
        backend.setMode("translation")
    if args.file:
        # Startup read is synchronous so automated captures cannot race document loading.
        from .document import load_document
        try:
            backend._loaded(load_document(args.file), args.file)
        except Exception as exc:
            backend.show_error(str(exc))
    elif not args.smoke_test and not args.screenshot:
        QTimer.singleShot(150, backend.restore_recovery)
    if args.media:
        backend.openMediaPath(args.media)
        QTimer.singleShot(900, lambda: backend.media_controller.seek(args.seek))
    initial_selection = None
    if backend.count:
        initial_selection = backend.select(min(backend.count - 1, max(0, args.select - 1)), 0)
    window.setProperty("startupChromeReady", True)
    result = {"code": 0}
    if args.smoke_test:
        QTimer.singleShot(600, app.quit)
    if args.screenshot:
        def capture():
            image = window.grabWindow()
            if image.isNull() or not image.save(args.screenshot):
                result["code"] = 1
            app.quit()
        QTimer.singleShot(3000 if not args.media else 6000, capture)
    code = app.exec()
    if args.diagnostics:
        from .media import ffmpeg_executable, ffprobe_executable
        from .visuals import libass_path
        report = {"version": __version__, "platform": sys.platform, "style": QQuickStyle.name(),
                  "applicationActive": app.applicationState() == Qt.ApplicationState.ApplicationActive, "windowActive": window.isActive(),
                  "ffmpeg": ffmpeg_executable(), "ffprobe": ffprobe_executable(),
                  "libass": libass_path(), "cues": backend.count, "mode": backend.mode, "selectedLine": backend.currentIndex + 1,
                  "initialSelectionApplied": initial_selection, "pendingDraft": bool(backend.draft), "media": backend.media_controller.path,
                  "videoFrameValid": bool(backend.media_controller._sink and backend.media_controller._sink.videoFrame().isValid()),
                  "audioBins": len(backend.media_controller.peaks), "spectrumShape": list(backend.media_controller.spectrum.shape), "keyframes": backend.media_controller.keyframeCount}
        report.update(chrome.diagnostics(window))
        Path(args.diagnostics).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # Explicitly release the QML tree while its context and media still exist.
    window.hide()
    sidebar = window.findChild(QObject, 'nativeGlassSidebar')
    if sidebar:
        sidebar.detach()
    chrome.detach()
    shiboken6.delete(window)
    shiboken6.delete(engine)
    backend.shutdown()
    return code or result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
