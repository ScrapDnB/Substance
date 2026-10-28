"""Exercise real local analysis and capture the tool windows (no downloads)."""
import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--model', default=str(ROOT / 'build/transcription/models/ggml-tiny.bin'))
    parser.add_argument('--audio', default=str(ROOT / 'build/qa/editor-tools/speech.wav'))
    parser.add_argument('--video', default=str(ROOT / 'build/qa/editor-tools/cuts.mp4'))
    parser.add_argument('--output', default=str(ROOT / 'build/qa/editor-tools'))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['SUBSTANCE_DATA_DIR'] = str(output / 'state')
    if not args.native:
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    os.environ.setdefault('QT_FFMPEG_DECODING_HW_DEVICE_TYPES', ',')
    # Synchronous grabs of several native windows can stall the threaded loop.
    os.environ.setdefault('QSG_RENDER_LOOP', 'basic')
    from PySide6.QtCore import QObject, QUrl, QEventLoop, QTimer, QMetaObject, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    import shiboken6
    from substance.backend import Backend
    from substance.document import Document, Cue
    from substance.images import ProjectImageProvider
    from substance import visuals  # noqa: F401
    app = QApplication([])
    QQuickStyle.setStyle('macOS' if args.native else 'Fusion')
    backend = Backend()
    messages = []
    handler = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(backend))
    engine.rootContext().setContextProperty('backend', backend)
    chrome = None
    if args.native:
        from substance.macos import MacOSIntegration
        chrome = MacOSIntegration(backend, app)
        engine.setInitialProperties({'macOSIntegration': chrome})
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    if chrome:
        chrome.configure(window)
    dialog = window.findChild(QObject, 'editorToolsDialog')
    def wait(ms=100):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()
    def until(predicate, seconds=60):
        deadline = time.monotonic() + seconds
        while not predicate() and time.monotonic() < deadline:
            wait(50)
        assert predicate(), backend.tools.status
    def capture(item, name):
        wait(200)
        assert item.grabWindow().save(str(output / name))
    report = {}
    try:
        doc = Document()
        for start, end, text, actor in [(500, 2800, 'And so my fellow Americans', 'Speaker'),
                                      (3900, 4900, 'ask  not', 'Speaker'),
                                      (5700, 8200, 'what your country can do for you', 'Speaker'),
                                      (8500, 10800, 'ask what you can do for your country', 'Speaker'),
                                      (5800, 7200, 'Overlapping dialogue', 'Other')]:
            c = Cue(start=start, end=end, text=text, original=text, character=actor)
            doc.register_source(c)
            doc.cues.append(c)
        backend._set_document(doc, '')
        backend.select(0)
        backend.openChecks()
        backend.tools.analyze('checks', {'timing': False})
        capture(dialog, 'checks.png')
        assert backend.tools.apply(), backend.tools.status
        backend.undo()
        dialog.close()
        backend.tools.setDisplayMode('wave')
        backend.media_controller.open(args.audio)
        until(lambda: len(backend.media_controller.peaks) > 0, 15)
        capture(window, 'tracks.png')
        backend.media_controller.open(args.video)
        until(lambda: backend.media.hasVideo, 15)
        backend.openScenes()
        backend.tools.analyze('scenes', {'threshold': 10})
        until(lambda: not backend.tools.busy)
        assert backend.tools.canApply, backend.tools.status
        report['detectedCuts'] = [r['time'] for r in backend.tools.sceneRows]
        assert report['detectedCuts'] == [1000, 2000], report
        capture(dialog, 'scenes.png')
        assert backend.tools.apply(), backend.tools.status
        backend.undo()
        assert not backend.media_controller.shot_changes
        dialog.close()
        backend.media_controller.open(args.audio)
        until(lambda: backend.media.duration > 0, 15)
        target = backend.speech.directory / 'ggml-tiny.bin'
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.symlink_to(Path(args.model).resolve())
        backend.openAlignment()
        dialog = window.findChild(QObject, "alignmentDialog")
        # Use the actual UI model choice too, for an accurate capture.
        model_widget = dialog.findChild(QObject, 'alignmentModel')
        if model_widget:
            model_widget.setProperty('currentIndex', 0)
        dialog.findChild(QObject, 'alignmentScope').setProperty('currentIndex', 2)
        dialog.findChild(QObject, 'alignmentLanguage').setProperty('currentIndex', 2)
        dialog.findChild(QObject, 'alignmentSearchWindow').setProperty('value', 1500)
        dialog.findChild(QObject, 'alignmentCpu').setProperty('checked', True)
        capture(dialog, 'alignment-setup.png')
        dialog.findChild(QObject, 'alignmentAdvancedToggle').setProperty('checked', True)
        capture(dialog, 'alignment-advanced.png')
        dialog.findChild(QObject, 'alignmentAdvancedToggle').setProperty('checked', False)
        QMetaObject.invokeMethod(dialog, 'runAnalysis')
        until(lambda: not backend.tools.busy, 90)
        report['alignment'] = backend.tools.rows
        assert any(r['applicable'] for r in report['alignment']), backend.tools.status
        capture(dialog, 'alignment.png')
        before_text = [c.output_text for c in backend.editor.document.cues]
        before_times = [(c.start, c.end) for c in backend.editor.document.cues]
        assert backend.tools.apply(), backend.tools.status
        assert [c.output_text for c in backend.editor.document.cues] == before_text
        backend.undo()
        assert [(c.start, c.end) for c in backend.editor.document.cues] == before_times
        report['undoAndTextPreservation'] = True
        report['qmlErrors'] = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign'))]
        assert not report['qmlErrors'], report['qmlErrors']
        if chrome:
            report.update(chrome.diagnostics(window))
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), 'utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'alignment'}, ensure_ascii=False))
    finally:
        dialog.close()
        window.hide()
        if chrome:
            sidebar = window.findChild(QObject, 'nativeGlassSidebar')
            if sidebar:
                sidebar.detach()
            chrome.detach()
        shiboken6.delete(window)
        shiboken6.delete(engine)
        backend.shutdown()
        qInstallMessageHandler(handler)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
