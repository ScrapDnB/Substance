"""Capture the streamlined tool windows using local media/models, without downloads."""
import argparse
from copy import deepcopy
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
    parser.add_argument('--theme', choices=['light', 'dark'], default='light')
    parser.add_argument('--models', default=str(ROOT / 'build/transcription/models'))
    parser.add_argument('--audio', default=str(ROOT / 'build/qa/editor-tools/speech.wav'))
    parser.add_argument('--output', default=str(ROOT / 'build/qa/tool-dialogs'))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['SUBSTANCE_DATA_DIR'] = str(output / 'state')
    os.environ['QSG_RENDER_LOOP'] = 'basic'
    os.environ['QT_FFMPEG_DECODING_HW_DEVICE_TYPES'] = ','
    if not args.native:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
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
    b = Backend()
    b.preference('theme', args.theme)
    b.speech.directory = Path(args.models).resolve()
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.rootContext().setContextProperty('backend', b)
    chrome = None
    if args.native:
        from substance.macos import MacOSIntegration
        chrome = MacOSIntegration(b, app)
        engine.setInitialProperties({'macOSIntegration': chrome})
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    if chrome:
        chrome.configure(window)

    def wait(ms=100):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(predicate, timeout=60):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            wait(50)
        assert predicate(), b.tools.status + ' / ' + b.speech.status

    def capture(dialog, name):
        wait(150)
        assert dialog.grabWindow().save(str(output / name))

    report = {'theme': args.theme, 'native': args.native,
              'renderer': os.environ.get('QT_QUICK_BACKEND', 'default')}
    try:
        document = Document()
        for start, end, text in [(500, 2800, 'And so my fellow Americans'),
                                 (3900, 4900, 'ask  not !'),
                                 (5700, 8200, 'what your country can do for you'),
                                 (8500, 10800, 'ask what you can do for your country')]:
            cue = Cue(start=start, end=end, text=text, original=text, character='Speaker')
            document.register_source(cue)
            document.cues.append(cue)
        b._set_document(document, '')
        b.select(0)
        b.media_controller.open(str(Path(args.audio).resolve()))
        until(lambda: b.media.duration > 0 and len(b.media_controller.peaks) > 0, 15)
        b.openChecks()
        dialog = window.findChild(QObject, 'editorToolsDialog')
        dialog.resize(1280, 900)
        b.tools.analyze('checks', {'timing': False})
        capture(dialog, 'checks-' + args.theme + '.png')
        dialog.resize(800, 720)
        dialog.findChild(QObject, 'toolsAdvancedToggle').setProperty('checked', True)
        capture(dialog, 'checks-small.png')
        dialog.close()
        b.editor.update(0, end=3800, text='And so my fellow Americans ask not what your country can do for you but what you can do for your country.')
        b.tools.open('split')
        dialog.resize(1280, 900)
        b.tools.analyze('split', {'width': 24, 'minimum': 500})
        capture(dialog, 'reflow-' + args.theme + '.png')
        report['splitCues'] = len(b.tools.preview['afterCues'])
        dialog.close()
        b._set_document(deepcopy(document), '')
        b.openAlignment()
        dialog = window.findChild(QObject, 'alignmentDialog')
        dialog.resize(1280, 900)
        dialog.findChild(QObject, 'alignmentModel').setProperty('currentIndex', 0)
        dialog.findChild(QObject, 'alignmentScope').setProperty('currentIndex', 2)
        dialog.findChild(QObject, 'alignmentLanguage').setProperty('currentIndex', 2)
        dialog.findChild(QObject, 'alignmentSearchWindow').setProperty('value', 1500)
        dialog.findChild(QObject, 'alignmentCpu').setProperty('checked', True)
        capture(dialog, 'alignment-setup.png')
        QMetaObject.invokeMethod(dialog, 'runAnalysis')
        until(lambda: not b.tools.busy, 90)
        assert b.tools.analysisReady and not b.tools.error, b.tools.status
        capture(dialog, 'alignment-' + args.theme + '.png')
        report['alignment'] = b.tools.summary
        dialog.resize(800, 720)
        dialog.setProperty('stage', 0)
        dialog.findChild(QObject, 'alignmentAdvancedToggle').setProperty('checked', True)
        capture(dialog, 'alignment-small.png')
        dialog.close()
        b.openTranscription()
        dialog = window.findChild(QObject, 'transcriptionDialog')
        dialog.resize(1280, 900)
        dialog.findChild(QObject, 'speechModel').setProperty('currentIndex', 0)
        dialog.findChild(QObject, 'speechLanguage').setProperty('currentIndex', 2)
        dialog.findChild(QObject, 'speechCpuOnly').setProperty('checked', True)
        capture(dialog, 'speech-setup.png')
        QMetaObject.invokeMethod(dialog, 'startRecognition')
        assert b.speech.running, b.speech.status
        until(lambda: not b.speech.running, 90)
        assert not b.speech.error and b.speech.previewRows, b.speech.status
        assert dialog.isVisible()
        report['recognition'] = {'phrases': len(b.speech.previewRows), 'windowStayedOpen': dialog.isVisible()}
        capture(dialog, 'speech-' + args.theme + '.png')
        dialog.resize(800, 720)
        dialog.findChild(QObject, 'speechAdvancedToggle').setProperty('checked', True)
        capture(dialog, 'speech-small.png')
        report['qmlErrors'] = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign'))]
        assert not report['qmlErrors'], report['qmlErrors']
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False))
        dialog.close()
    finally:
        b.shutdown()
        window.hide()
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
