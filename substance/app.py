"""Cross-platform native-styled desktop entry point."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import sys
import json

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, QEvent, Signal, qVersion
from PySide6.QtGui import QIcon
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication
import shiboken6

from . import __version__
from .backend import Backend
from . import visuals  # noqa: F401 - registers the Substance QML module.
from .macos import MacOSIntegration
from .stdio import binary_stdio


class DesktopApplication(QApplication):
    fileRequested = Signal(str)

    def __init__(self, argv):
        self.pending_files = []
        self.accept_files = False
        self.main_window = None
        super().__init__(argv)

    def event(self, event):
        if event.type() == QEvent.Type.Quit and self.main_window and self.main_window.isVisible():
            # Dock/system Quit must use the same save/acknowledgement path as X.
            self.main_window.close()
            event.ignore()
            return True
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
    parser.add_argument("--online-capabilities", action="store_true")
    parser.add_argument("--online-stdin", action="store_true")
    parser.add_argument("--online-resume", action="store_true")
    parser.add_argument("--qml-preview", action="store_true", help="Enable QML live preview for source development")
    parser.add_argument("-qmljsdebugger", dest="qml_debugger", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.qml_debugger and not args.qml_preview:
        parser.error("-qmljsdebugger requires --qml-preview")
    if args.qml_preview:
        if getattr(sys, "frozen", False):
            parser.error("QML preview is available only when running from source")
        if tuple(map(int, qVersion().split(".")[:2])) < (6, 12):
            parser.error("QML preview requires PySide6 / Qt 6.12 or newer")
        from PySide6.QtQml import QQmlDebuggingEnabler
        qml_debugging = QQmlDebuggingEnabler()  # Keep alive for the application lifetime.
    if args.online_capabilities:
        from .repositories import online_client
        online_client()
        stream = binary_stdio(sys.stdout, output=True)
        stream.write(json.dumps({"protocol": 1, "document_schema": 1, "version": __version__, "capabilities": ["document_cas_v1"]}).encode("utf-8"))
        stream.flush()
        return 0
    launch = None
    if args.online_stdin:
        raw = binary_stdio(sys.stdin).read(16385)
        if len(raw) > 16384:
            return 2
        launch = json.loads(raw)
        if not isinstance(launch, dict) or args.file:
            return 2
        if "media_path" in launch and not isinstance(launch["media_path"], str):
            return 2
        for field in ("server_url", "project_id", "episode_id", "episode_name", "code"):
            if not isinstance(launch.get(field), str) or not launch[field]:
                return 2
    qt_arguments = [sys.argv[0]]
    if args.qml_debugger:
        qt_arguments.append("-qmljsdebugger=" + args.qml_debugger)
    app = DesktopApplication(qt_arguments)
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
    from .images import ProjectImageProvider
    engine.addImageProvider("project", ProjectImageProvider(backend))
    engine.rootContext().setContextProperty("backend", backend)
    engine.setInitialProperties({"macOSIntegration": chrome, "startupChromeReady": False})
    engine.load(QUrl.fromLocalFile(str(Path(__file__).parent / "qml" / "Main.qml")))
    if not engine.rootObjects():
        backend.shutdown()
        return 1
    window = engine.rootObjects()[0]
    app.main_window = window
    # An accepted close completes the application lifecycle even if another
    # native/tool window prevents Qt's automatic last-window quit.
    window.closeAccepted.connect(app.quit, Qt.ConnectionType.QueuedConnection)
    chrome.configure(window)
    app.fileRequested.connect(backend.openPath)
    app.accept_files = True
    for pending_file in app.pending_files:
        QTimer.singleShot(0, lambda path=pending_file: backend.openPath(path))
    if args.translation:
        backend.setMode("translation")
    if launch:
        QTimer.singleShot(0, lambda: backend.online.connect(launch))
    elif args.online_resume:
        QTimer.singleShot(0, backend.online.resume)
    elif args.file:
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
    native_diagnostics = None

    def finish_smoke():
        nonlocal native_diagnostics
        if args.diagnostics:
            # Qt releases the native content view when the window closes.
            # Capture AppKit pointers while the window is still alive.
            native_diagnostics = chrome.diagnostics(window)
        app.quit()

    if args.smoke_test:
        QTimer.singleShot(600, finish_smoke)
    if args.screenshot:
        def capture():
            image = window.grabWindow()
            if image.isNull() or not image.save(args.screenshot):
                result["code"] = 1
            finish_smoke()
        QTimer.singleShot(3000 if not args.media else 6000, capture)
    code = app.exec()
    if args.diagnostics:
        from .media import ffmpeg_executable, ffprobe_executable
        from .visuals import libass_path
        from .transcription import whisper_executable, vad_model_path
        report = {"version": __version__, "qtVersion": qVersion(), "qmlPreview": args.qml_preview,
                  "platform": sys.platform, "style": QQuickStyle.name(),
                  "applicationActive": app.applicationState() == Qt.ApplicationState.ApplicationActive, "windowActive": window.isActive(),
                  "ffmpeg": ffmpeg_executable(), "ffprobe": ffprobe_executable(), "whisper": whisper_executable(),
                  "speechVAD": str(vad_model_path() or ''),
                  "libass": libass_path(), "cues": backend.count, "mode": backend.mode, "selectedLine": backend.currentIndex + 1,
                  "initialSelectionApplied": initial_selection, "pendingDraft": bool(backend.draft), "media": backend.media_controller.path,
                  "videoFrameValid": bool(backend.media_controller._sink and backend.media_controller._sink.videoFrame().isValid()),
                  "audioBins": len(backend.media_controller.peaks), "spectrumShape": list(backend.media_controller.spectrum.shape), "keyframes": backend.media_controller.keyframeCount}
        report.update(native_diagnostics if native_diagnostics is not None else chrome.diagnostics(window))
        report["online"] = {"active": backend.online.active, "pending": backend.online.pending,
                            "revision": backend.online.revision,
                            "sessionProtected": backend.online._session_persisted}
        Path(args.diagnostics).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    # Explicitly release the QML tree while its context and media still exist.
    window.hide()
    sidebar = window.findChild(QObject, 'nativeGlassSidebar')
    if sidebar:
        sidebar.detach()
    chrome.detach()
    app.main_window = None
    backend.media_controller.shutdown()
    shiboken6.delete(window)
    shiboken6.delete(engine)
    backend.shutdown()
    return code or result["code"]


if __name__ == "__main__":
    raise SystemExit(main())
