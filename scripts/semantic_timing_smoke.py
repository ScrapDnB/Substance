"""Exercise real Whisper + multilingual ONNX, preview, apply, save and Undo.

Defaults use the existing local JFK audio/model QA fixtures. No downloads and
no open editor or source document is modified. --native captures macOS controls.
"""
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
    parser.add_argument('--audio', default=str(ROOT / 'build/qa/editor-tools/speech.wav'))
    parser.add_argument('--speech-models', default=str(ROOT / 'build/transcription/models'))
    parser.add_argument('--semantic-models', default=str(ROOT / 'build/semantic-timing/models'))
    parser.add_argument('--output', default=str(ROOT / 'build/qa/semantic-timing'))
    parser.add_argument('--dub')
    parser.add_argument('--episode', default='1')
    parser.add_argument('--rows', help='Use this source-row slice from --dub, e.g. 63:65 (zero based)')
    parser.add_argument('--model', default='tiny')
    parser.add_argument('--mode', choices=('sentences', 'precise'), default='sentences')
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
    from substance.document import Document, Cue, save_document, load_document, export_document, plain_text
    from substance.images import ProjectImageProvider
    from substance.semantic_timing import sentence_spans, script_text
    from substance import visuals  # noqa: F401
    app = QApplication([])
    QQuickStyle.setStyle('macOS' if args.native else 'Fusion')
    b = Backend()
    b.speech.directory = Path(args.speech_models)
    b.alignment_models.directory = Path(args.semantic_models)
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]

    def wait(ms=50):
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    def until(predicate, timeout=240):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            wait()
        assert predicate(), b.tools.status

    report = {'native': args.native, 'mode': args.mode}
    try:
        if args.dub:
            project = json.loads(Path(args.dub).read_text())
            episode = project['script_storage']['episodes'][args.episode]
            assert not episode.get('edit_blocks'), 'Diagnostic import requires an unedited source episode'
            sample = Document()
            if args.rows:
                sample.media['path'] = str(Path(args.audio).resolve())
            for row in episode['source_lines']:
                cue = Cue(id=row['id'], source_ids=[row['id']], start=round(row['start']*1000),
                          end=round(row['end']*1000), text=row['text'], original=row['text'],
                          character=row.get('character', ''))
                sample.cues.append(cue)
                sample.source_lines[cue.id] = deepcopy(row)
                text = ' '.join(plain_text(cue.text).split())
                assert ''.join(''.join(text[a:z].split()) for a, z in sentence_spans(text)) == ''.join(text.split())
            save_document(sample, output / 'moby-source.substance')
            report['sample'] = {'rows': len(sample.cues), 'maxCharacters': max(len(c.text) for c in sample.cues),
                                'over200': sum(len(c.text) > 200 for c in sample.cues), 'losslessSegmentation': True}
        text = ('Итак, дорогие американцы, не спрашивайте, что ваша страна может сделать для вас. '
                'Спросите, что вы можете сделать для своей страны.')
        if args.rows:
            begin, end = map(int, args.rows.split(':'))
            doc = deepcopy(sample)
            doc.cues = doc.cues[begin:end]
            text = ' '.join(c.text for c in doc.cues)
            report['sourceRows'] = args.rows
        else:
            doc = Document()
            cue = Cue(start=0, end=11000, text=text, original=text, character='Speaker')
            doc.register_source(cue)
            doc.cues = [cue]
        doc.media['path'] = str(Path(args.audio).resolve())
        b._set_document(doc, '')
        b.media_controller.open(str(Path(args.audio).resolve()))
        until(lambda: b.media.duration > 0 and not b.media.busy, 30)
        snapshot = deepcopy(b.editor.document)
        b.openSemanticTiming()
        dialog = window.findChild(QObject, 'semanticTimingDialog')
        dialog.findChild(QObject, 'semanticMode').setProperty('currentIndex', 1 if args.mode == 'precise' else 0)
        dialog.findChild(QObject, 'semanticAudioLanguage').setProperty('currentIndex', 2)
        dialog.findChild(QObject, 'semanticTextLanguage').setProperty('currentIndex', 1)
        dialog.findChild(QObject, 'semanticSpeechModel').setProperty('currentIndex',
            next(i for i, model in enumerate(b.speech.models) if model['id'] == args.model))
        dialog.findChild(QObject, 'semanticCpu').setProperty('checked', True)
        if args.rows:
            from substance.timecode import format_time
            dialog.findChild(QObject, 'semanticStart').setProperty('text', format_time(max(0, doc.cues[0].start-1000)))
            dialog.findChild(QObject, 'semanticEnd').setProperty('text', format_time(min(b.media.duration, doc.cues[-1].end+1000)))
        dialog.resize(1280, 940)
        wait(150)
        assert dialog.grabWindow().save(str(output / 'setup.png'))
        assert dialog.property('ready'), messages
        started = time.monotonic()
        QMetaObject.invokeMethod(dialog, 'runAnalysis')
        task = b.tools._task
        until(lambda: not b.tools.busy)
        report['analysisSeconds'] = round(time.monotonic()-started, 3)
        if task is not None:
            (output / 'recognized.json').write_text(json.dumps(task.words, ensure_ascii=False, indent=2))
        (output / 'proposals.json').write_text(json.dumps(b.tools.rows, ensure_ascii=False, indent=2))
        assert b.tools.analysisReady and not b.tools.error, b.tools.status
        assert b.tools.preview['applicable'], b.tools.rows
        report['summary'] = b.tools.summary
        report['cues'] = b.tools.preview['afterCues']
        assert not b.tools.canApply
        wait(150)
        assert dialog.grabWindow().save(str(output / 'results.png'))
        dialog.resize(820, 700)
        wait(150)
        assert dialog.grabWindow().save(str(output / 'results-small.png'))
        b.tools.checkAll(True)
        assert b.tools.apply(), b.tools.status
        assert b.editor.document.source_lines == snapshot.source_lines
        assert ''.join(''.join(plain_text(c.output_text).split()) for c in b.editor.document.cues) == ''.join(script_text(text, True).split())
        assert all(c.translation and c.original for c in b.editor.document.cues)
        result = output / 'result.substance'
        save_document(b.editor.document, result)
        assert load_document(result) == b.editor.document
        export_document(b.editor.document, output / 'result.srt')
        b.undo()
        assert b.editor.document == snapshot
        report['undo'] = report['saveRoundTrip'] = report['textPreserved'] = True
        report['qmlErrors'] = [m for m in messages if any(x in m for x in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign'))]
        assert not report['qmlErrors'], report['qmlErrors']
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
        print(json.dumps({key: value for key, value in report.items() if key != 'cues'} |
                         {'cueCount': len(report['cues'])}, ensure_ascii=False, indent=2))
    finally:
        b.shutdown()
        window.hide()
        shiboken6.delete(window)
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


if __name__ == '__main__':
    main()
