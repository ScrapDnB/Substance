"""Render manual timing tools with local audio for visual review."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', action='store_true')
    parser.add_argument('--theme', choices=['light', 'dark'], default='light')
    parser.add_argument('--audio', default=str(ROOT / 'build/qa/editor-tools/speech.wav'))
    parser.add_argument('--output', default=str(ROOT / 'build/qa/timing'))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    os.environ['SUBSTANCE_DATA_DIR'] = str(output / 'state')
    os.environ['QSG_RENDER_LOOP'] = 'basic'
    if not args.native:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import QObject, QUrl, QEventLoop, QTimer, QMetaObject, qInstallMessageHandler
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
    import shiboken6
    from substance.backend import Backend
    from substance.document import Cue, Document
    from substance import visuals  # noqa: F401
    app = QApplication([])
    QQuickStyle.setStyle('macOS' if args.native else 'Fusion')
    b = Backend()
    b.preference('theme', args.theme)
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    w = engine.rootObjects()[0]

    def wait(ms=100):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def capture(name):
        wait(150)
        assert d.grabWindow().save(str(output / name))

    try:
        doc = Document()
        for start, end, text in [(1000, 2800, 'Итак, дорогие друзья,'), (3900, 4900, 'не спрашивайте,'),
                                 (5700, 8200, 'что ваша страна может сделать для вас.'), (8500, 10800, 'Спросите, что вы можете сделать для своей страны.')]:
            c = Cue(start=start, end=end, text=text, original=text)
            doc.register_source(c)
            doc.cues.append(c)
        b._set_document(doc, '')
        if Path(args.audio).is_file():
            b.openMediaPath(args.audio)
            for _ in range(100):
                wait(50)
                if len(b.media_controller.peaks):
                    break
        b.openShift()
        d = w.findChild(QObject, 'shiftDialog')
        d.resize(1080, 880)
        d.findChild(QObject, 'shiftAmount').setProperty('value', 500)
        capture('shift-' + args.theme + '.png')
        d.resize(800, 660)
        capture('shift-small-' + args.theme + '.png')
        d.close()
        b.openPointSync()
        d.resize(1080, 880)
        b.timing.setPoint('00:00:01.400')
        b.timing.selectPreview(3)
        b.timing.setPoint('00:00:09.700')
        QMetaObject.invokeMethod(d, 'loadTarget')
        capture('points-' + args.theme + '.png')
        d.resize(800, 660)
        capture('points-small-' + args.theme + '.png')
        errors = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'is not a function', 'Non-existent'))]
        assert not errors, errors
        (output / 'report.json').write_text(json.dumps({'native': args.native, 'theme': args.theme, 'points': b.timing.points, 'canApply': b.timing.canApply, 'errors': errors}, ensure_ascii=False, indent=2))
    finally:
        b.shutdown()
        d.close()
        w.hide()
        shiboken6.delete(w)
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


if __name__ == '__main__':
    main()
