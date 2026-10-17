"""Exercise real local inference, streaming GUI updates and selective undo.

Example: python scripts/transcription_smoke.py --models build/transcription/models
         --media build/transcription/jfk.wav --cpu
Models and input are supplied explicitly; this script never downloads anything.
"""
from pathlib import Path
import argparse
import json
import os
import sys
import tempfile
import wave

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--models', required=True)
    parser.add_argument('--media', required=True, help='16 kHz mono PCM WAV; repeated to exercise streaming')
    parser.add_argument('--cpu', action='store_true')
    parser.add_argument('--stop-after-first', action='store_true', help='Verify stopping a real subprocess after the first editable batch')
    parser.add_argument('--qml', action='store_true', help='Also load and capture the main window and settings dialog')
    args = parser.parse_args()
    from PySide6.QtCore import QEvent, QObject, QTimer, QUrl, QMetaObject
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtWidgets import QApplication
    from PySide6.QtQuickControls2 import QQuickStyle
    from substance.backend import Backend
    from substance.document import save_document, load_document
    from substance.images import ProjectImageProvider
    from substance import visuals  # noqa: F401

    qa = ROOT / 'build/qa/transcription'
    qa.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='substance-speech-qa-') as directory:
        os.environ['SUBSTANCE_DATA_DIR'] = directory
        # Six repetitions exceed Whisper's 30-second window. A first batch
        # must become editable before the final decoding window completes.
        with wave.open(str(Path(args.media).resolve()), 'rb') as source:
            params, frames = source.getparams(), source.readframes(source.getnframes())
        audio = Path(directory) / 'speech.wav'
        with wave.open(str(audio), 'wb') as target:
            target.setparams(params)
            target.writeframes(frames * 6)
        app = QApplication([])
        QQuickStyle.setStyle('Fusion' if os.environ.get('QT_QPA_PLATFORM') == 'offscreen' else 'macOS' if sys.platform == 'darwin' else 'Fusion')
        backend = Backend()
        backend.speech.directory = Path(args.models).resolve()
        engine, window = None, None
        if args.qml:
            engine = QQmlApplicationEngine()
            engine.addImageProvider('project', ProjectImageProvider(backend))
            engine.rootContext().setContextProperty('backend', backend)
            engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
            assert engine.rootObjects(), 'QML did not load'
            window = engine.rootObjects()[0]
        backend.media_controller.open(str(audio))
        report = {'started': False, 'editedWhileRunning': False, 'timedOut': False}
        edited_id = ''

        def tick():
            nonlocal edited_id
            if not report['started']:
                if backend.media_controller.duration <= 0:
                    return
                if window:
                    dialog = window.findChild(QObject, 'transcriptionDialog')
                    QMetaObject.invokeMethod(dialog, 'open')
                    QTimer.singleShot(80, lambda: dialog.grabWindow().save(str(qa / 'dialog.png')))
                    QTimer.singleShot(100, dialog.close)
                assert backend.speech.start({'model': 'tiny', 'language': 'en', 'cpu': args.cpu, 'track': 0, 'width': 42})
                report['started'] = True
                return
            if backend.count and backend.speech.running and not edited_id:
                edited_id = backend.editor.document.cues[0].id
                backend.stage('text', 'Manual edit during recognition')
                assert backend.flush()
                report['editedWhileRunning'] = True
                if args.stop_after_first:
                    backend.speech.stop()
            if not backend.speech.running:
                timer.stop()
                report.update({'status': backend.speech.status, 'error': backend.speech.error,
                               'cues': backend.count, 'model': 'tiny', 'cpu': args.cpu,
                               'selection': backend.currentIndex, 'progress': backend.speech.progress})
                if window:
                    window.grabWindow().save(str(qa / 'main.png'))
                for suffix in ('.ass', '.substance'):
                    path = qa / ('recognized' + suffix)
                    save_document(backend.editor.document, path)
                    assert len(load_document(path).cues) == backend.count
                assert report['editedWhileRunning'], 'No editable batch arrived before completion'
                assert backend.editor.document.cues[0].text == 'Manual edit during recognition'
                backend.speech.discard()
                report['cuesAfterDiscard'] = backend.count
                assert backend.count == 1 and backend.editor.document.cues[0].id == edited_id
                app.quit()

        timer = QTimer(interval=50)
        def guarded_tick():
            try:
                tick()
            except Exception as exc:
                report['failure'] = repr(exc)
                timer.stop()
                app.quit()
        timer.timeout.connect(guarded_tick)
        timer.start()
        def timeout():
            report['timedOut'] = True
            app.quit()
        QTimer.singleShot(120000, timeout)
        app.exec()
        if window:
            window.hide()
            import shiboken6
            shiboken6.delete(engine)
            app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        backend.shutdown()
        (qa / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        name = 'report-' + ('cpu' if args.cpu else 'gpu') + ('-stopped' if args.stop_after_first else '') + '.json'
        (qa / name).write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return int(report['timedOut'] or report.get('error', True) or bool(report.get('failure')))


if __name__ == '__main__':
    raise SystemExit(main())
