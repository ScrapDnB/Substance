"""Exercise project dialogs and real video capture; write inspectable QA artifacts."""
from pathlib import Path
import json
import os
import sys
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
qa = root / 'build/qa/project'
qa.mkdir(parents=True, exist_ok=True)
os.environ['SUBSTANCE_DATA_DIR'] = tempfile.mkdtemp(prefix='substance-project-qa-')
from PySide6.QtCore import QObject, QEventLoop, QTimer, QUrl, QMetaObject, qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
import shiboken6
from substance.backend import Backend
from substance.document import load_document
from substance.images import ProjectImageProvider
from substance.macos import MacOSIntegration
from substance.media import ffmpeg_executable, process_options
from substance import visuals


def wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication([])
    app.setApplicationName('Substance Project QA')
    QQuickStyle.setStyle('macOS' if app.platformName() == 'cocoa' else 'Fusion')
    messages, checks = [], []
    handler = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    b = Backend()
    b._set_document(load_document(root / 'substance/resources/example.ass'), '')
    b._save_path(str(qa / 'demo.substance'))
    chrome = MacOSIntegration(b, app)
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.rootContext().setContextProperty('backend', b)
    engine.setInitialProperties({'macOSIntegration': chrome, 'startupChromeReady': False})
    window = None
    def check(value, name):
        if not value:
            raise AssertionError(name)
        checks.append(name)
        print(name, flush=True)
    def js(code):
        e = QQmlExpression(qmlContext(window), window, code)
        e.evaluate()
        check(not e.hasError(), code)
    def activate(name):
        wait(150)
        item = window.findChild(QObject, name)
        check(item is not None and item.property('enabled'), name + ' is enabled')
        # macOS-style buttons dispatch AppKit actions. Invoke their public Qt
        # signal here; actual pointer interaction is covered by the Fusion UI test.
        QTimer.singleShot(0, lambda: QMetaObject.invokeMethod(item, 'clicked'))
        wait(150)
    def screenshot(name, popup_name=''):
        check(window.grabWindow().save(str(qa / name)), name + ' captured')
    try:
        engine.load(QUrl.fromLocalFile(str(root / 'substance/qml/Main.qml')))
        check(bool(engine.rootObjects()), 'QML window loaded')
        window = engine.rootObjects()[0]
        chrome.configure(window)
        window.setProperty('startupChromeReady', True)
        window.requestActivate()
        wait(200)
        js("reviewCompose.create('note')")
        window.findChild(QObject, 'reviewComment').setProperty('text', 'Сохранять обращение на «вы».')
        activate('saveReview')
        check(b.currentReviews[0]['kind'] == 'note', 'Note created by dialog')
        js("reviewCompose.create('proposal')")
        window.findChild(QObject, 'proposedText').setProperty('text', 'You came after all.\nI was waiting.')
        window.findChild(QObject, 'reviewComment').setProperty('text', 'Более естественная формулировка.')
        activate('saveReview')
        proposal_id = b.currentReviews[0]['id']
        check(b.currentReviews[0]['state'] == 'open', 'Proposal remains separate from text')
        b.openReviews(); wait(100); screenshot('reviews.png', 'reviewsDialog')
        js('reviewsDialog.close()')
        b.reviewAction(proposal_id, 'apply')
        check(b.current['editText'].startswith('You came'), 'Proposal applied')
        b.undo()
        check(b.currentReviews[0]['state'] == 'open', 'Undo restores proposal and text')
        clip = qa / 'capture-test.mp4'
        subprocess.run([ffmpeg_executable(), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=640x360:rate=24:duration=3', '-c:v', 'libx264', '-y', str(clip)], check=True, timeout=30, **process_options())
        b.openMediaPath(str(clip))
        for _ in range(100):
            wait(50)
            if b.media_controller._sink and b.media_controller._sink.videoFrame().isValid():
                break
        check(b.media_controller._sink.videoFrame().isValid(), 'Real decoded video frame ready')
        b.media_controller.seek(1000)
        b.capturePortrait(b.current['characterId'])
        for _ in range(60):
            wait(50)
            if window.findChild(QObject, 'portraitCropDialog').property('visible'):
                break
        check(window.findChild(QObject, 'portraitCropDialog').property('visible'), 'Capture opens crop dialog')
        check(900 <= b.captureInfo['time'] <= 1100, 'Capture uses frame after seek')
        js('portraitCropDialog.setRatio(1)')
        wait(100); screenshot('crop.png', 'portraitCropDialog')
        activate('savePortraitCrop')
        check(bool(b.currentPortraitUrl), 'Crop saves embedded portrait')
        wait(100); screenshot('characters.png', 'characterDialog')
        card = b.currentCard
        cid, pid = card['id'], card['portraits'][0]['id']
        js('characterDialog.close()')
        b.recropPortrait(cid, pid); wait(100)
        check(b.captureInfo['width'] == 640, 'Original capture retained for recrop')
        js('portraitCropDialog.close()')
        b.setMode('translation'); wait(200)
        check(b.media_controller._sink.videoFrame().isValid(), 'Paused frame survives mode switch')
        screenshot('workspace.png')
        b.save()
        restored = load_document(b.path)
        check(restored.images == b.editor.document.images and len(restored.reviews) == 2, 'Project data survives disk roundtrip')
        problems = [m for m in messages if any(word in m for word in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'Failed to get image', 'Duplicate method'))]
        check(not problems, 'No QML runtime errors: ' + repr(problems))
        (qa / 'checks.json').write_text(json.dumps({'checks': checks, 'platform': app.platformName(), 'captureTime': b.captureInfo.get('time'), 'version': b.version, 'messages': messages}, ensure_ascii=False, indent=2))
    finally:
        if window:
            window.hide()
            sidebar = window.findChild(QObject, 'nativeGlassSidebar')
            if sidebar:
                sidebar.detach()
            chrome.detach()
            shiboken6.delete(window)
        shiboken6.delete(engine)
        b.shutdown()
        qInstallMessageHandler(handler)
    print(f'{len(checks)} project checks passed; {qa}', flush=True)


if __name__ == '__main__':
    main()
