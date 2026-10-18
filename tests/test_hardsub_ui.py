from pathlib import Path
import os

import cv2
import numpy as np
import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.hardsub import image_url
from substance.images import ProjectImageProvider
from substance.tool_jobs import video_identity
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def ui(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path / 'data'))
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    b = Backend()
    b.hardsub.refreshEngine = lambda: None
    messages = []
    handler = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    w = engine.rootObjects()[0]
    yield b, w, tmp_path
    b.shutdown()
    w.hide()
    shiboken6.delete(engine)
    qInstallMessageHandler(handler)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'is not a function', 'Non-existent'))], messages


def test_hardsub_dialog_accessible_and_missing_engine_guarded(ui):
    b, w, _ = ui
    assert w.findChild(QObject, 'hardsubMenuItem')
    assert w.findChild(QObject, 'hardsubEmptyDocument')
    b.openHardsub()
    QTest.qWait(30)
    dialog = w.findChild(QObject, 'hardsubDialog')
    assert dialog.property('visible') and w.property('modalOpen')
    assert not w.findChild(QObject, 'hardsubAnalyzeButton').property('enabled')
    assert not w.findChild(QObject, 'hardsubApplyButton').property('enabled')
    assert w.findChild(QObject, 'hardsubRegionY').property('value') == 65
    dialog.close()
    assert not w.property('modalOpen')


def test_review_edits_survive_selection_changes_and_import_to_translation(ui, monkeypatch):
    from copy import deepcopy
    b, w, tmp_path = ui
    media_path = tmp_path / 'video.mp4'
    media_path.write_bytes(b'video identity')
    b.media_controller.path = str(media_path)
    monkeypatch.setattr(type(b.media_controller), 'hasVideo', property(lambda self: True))
    monkeypatch.setattr(type(b.media_controller), 'duration', property(lambda self: 10000))
    b.hardsub.previewFrame = lambda: None
    b.openHardsub()
    dialog = w.findChild(QObject, 'hardsubDialog')
    frame = np.zeros((360, 640, 3), np.uint8)
    cv2.putText(frame, 'A burned in subtitle', (35, 305), cv2.FONT_HERSHEY_SIMPLEX, .95, (255, 255, 255), 2, cv2.LINE_AA)
    preview = image_url(frame)
    ocr = b.hardsub
    ocr._snapshot = deepcopy(b.editor.document)
    ocr._editor, ocr._context = b.editor, ocr._media_context()
    ocr._identity = video_identity(media_path)
    ocr._preview, ocr._preview_context = preview, ocr._context
    ocr._rows = [{'start': 1000 + i * 2000, 'end': 2000 + i * 2000,
                  'text': text, 'confidence': .95, 'checked': True, 'preview': preview}
                 for i, text in enumerate(['A burned in subtitle', 'A second subtitle'])]
    ocr.changed.emit()
    QTest.qWait(120)
    correction = w.findChild(QObject, 'hardsubCorrection')
    assert correction.property('text') == 'A burned in subtitle'
    correction.setProperty('text', 'Corrected source')
    # Checking a different row must not wipe the open correction draft.
    ocr.check(1, False)
    QTest.qWait(20)
    assert correction.property('text') == 'Corrected source'
    dialog.chooseRow(1)
    assert ocr.rows[0]['text'] == 'Corrected source'
    dialog.chooseRow(0)
    assert correction.property('text') == 'Corrected source'
    if os.environ.get('SUBSTANCE_HARDSUB_SCREENSHOTS'):
        folder = Path(os.environ['SUBSTANCE_HARDSUB_SCREENSHOTS'])
        folder.mkdir(parents=True, exist_ok=True)
        QTest.qWait(50)
        assert dialog.grabWindow().save(str(folder / 'hardsub-results.png'))
    w.findChild(QObject, 'hardsubForTranslation').setProperty('checked', True)
    w.findChild(QObject, 'hardsubApplyButton').clicked.emit()
    QTest.qWait(20)
    assert b.count == 1 and b.editor.document.cues[0].original == 'Corrected source'
    assert b.editor.document.cues[0].translation == '' and b.mode == 'translation'
    b.undo()
    assert b.count == 0
    dialog.close()
