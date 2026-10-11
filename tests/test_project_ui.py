import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import json
import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, QPointF, Qt, qInstallMessageHandler
from PySide6.QtGui import QImage, QColor
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from substance.backend import Backend
from substance.document import load_document
from substance.images import ProjectImageProvider, decode_image, frame_image, crop_image
from substance import visuals

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle('Fusion')
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    backend = Backend()
    backend._set_document(load_document(ROOT / 'substance/resources/example.ass'), '')
    assert backend._save_path(str(tmp_path / 'work.substance'))
    yield app, backend
    backend.shutdown()


def test_project_gate_and_cancel_preserves_document(bridge, monkeypatch):
    app, b = bridge
    b.path = ''
    b.editor.project_mode = False
    before = b.editor.document.to_dict()
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: ('', ''))
    assert not b.addReview('note', 'Note', '')
    assert b.editor.document.to_dict() == before
    assert not b.isProject


def test_warning_filters_cache_and_undo(bridge):
    app, b = bridge
    b.editor.update(0, text='A' * 90, end=3200)
    b._refresh()
    b.setReviewSetting('readingSpeed', False)
    b.setFilter('warnings')
    assert 0 in b.model.visible
    b.setReviewSetting('lineLength', False)
    assert 0 not in b.model.visible
    assert not b.current['issues']
    b.undo()
    assert 0 in b.model.visible
    b.save()
    assert load_document(b.path).review_settings.get('lineLength', True)


def test_live_notes_filters_archives_and_recovery(bridge):
    app, b = bridge
    assert b.addReview('note', 'Check name', '')
    assert b.counts['notes'] == 1
    b.setFilter('notes')
    assert b.visibleCount == 1
    b.reviewAction(b.currentReviews[0]['id'], 'resolved')
    assert b.visibleCount == 0
    b.undo()
    b.deleteLines()
    assert b.reviewEntries[0]['archived']
    b.autosave()
    data = json.loads(b.recovery_path.read_text())
    assert data['reviews'][0]['text'] == 'Check name'


def test_crop_resources_gallery_roundtrip_undo_and_recrop(bridge):
    app, b = bridge
    card_id = b.editor.document.characters[0].id
    image = QImage(320, 180, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    b._begin_crop(image, {'cardId': card_id, 'media_path': '/missing/video.mp4', 'time': 1234})
    assert b.savePortrait(card_id, '', .25, .25, .5, .5, True)
    card = b.editor.document.characters[0]
    portrait = card.portraits[0]
    decoded = decode_image(b.editor.document.images[portrait['image']])
    assert decoded.size().width() == 160 and decoded.size().height() == 90
    b.save()
    restored = load_document(b.path)
    assert restored.images == b.editor.document.images
    assert restored.characters[0].portraits[0]['time'] == 1234
    b.recropPortrait(card_id, portrait['id'])
    assert b.captureInfo['width'] == 320
    assert b.savePortrait(card_id, '', 0, 0, 1, 1, True)
    assert len(b.editor.document.characters[0].portraits) == 1
    b.undo()
    assert b.editor.document.characters[0].portraits[0]['crop'] == [.25, .25, .5, .5]
    b.portraitAction(card_id, portrait['id'], 'delete')
    assert not b.editor.document.images
    b.undo()
    assert b.editor.document.images


def test_new_character_and_portrait_are_one_transaction(bridge):
    app, b = bridge
    b._begin_crop(QImage(60, 60, QImage.Format.Format_RGB32), {})
    count = len(b.editor.document.characters)
    assert b.savePortrait('', 'New person', 0, 0, 1, 1, True)
    assert len(b.editor.document.characters) == count+1
    b.undo()
    assert len(b.editor.document.characters) == count
    assert not b.editor.document.images


def test_frame_rotation_and_mirror_and_crop_bounds(bridge):
    from PySide6.QtMultimedia import QVideoFrame, QtVideo
    image = QImage(80, 40, QImage.Format.Format_RGB32)
    image.fill(QColor('red'))
    for x in range(40, 80):
        for y in range(40):
            image.setPixelColor(x, y, QColor('blue'))
    frame = QVideoFrame(image)
    frame.setRotation(QtVideo.Rotation.Clockwise90)
    rotated = frame_image(frame)
    assert (rotated.width(), rotated.height()) == (40, 80)
    frame.setRotation(QtVideo.Rotation.None_)
    frame.setMirrored(True)
    assert frame_image(frame).pixelColor(0, 0) == QColor('blue')
    with pytest.raises(ValueError):
        crop_image(image, [.9, 0, .5, 1])


def test_qml_review_and_portrait_workflow(bridge):
    app, b = bridge
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.rootContext().setContextProperty('backend', b)
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
        assert engine.rootObjects(), messages
        w = engine.rootObjects()[0]
        QTest.qWait(100)
        def js(code):
            expression = QQmlExpression(qmlContext(w), w, code)
            result = expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            return result
        def click(name):
            item = w.findChild(QObject, name)
            assert item is not None and item.property('enabled')
            p = item.mapToScene(QPointF(item.width()/2, item.height()/2)).toPoint()
            QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, p)
            QTest.qWait(80)
        js("reviewCompose.create('note')")
        w.findChild(QObject, 'reviewComment').setProperty('text', 'A note from the UI')
        click('saveReview')
        assert b.currentReviews[0]['text'] == 'A note from the UI'
        js("reviewCompose.create('proposal')")
        w.findChild(QObject, 'proposedText').setProperty('text', 'New wording')
        click('saveReview')
        assert b.currentReviews[0]['replacement'] == 'New wording'
        b.openReviews()
        QTest.qWait(80)
        assert w.findChild(QObject, 'reviewList').property('count') == 2
        js('reviewsDialog.close()')
        image = QImage(320, 180, QImage.Format.Format_RGB32)
        image.fill(QColor('green'))
        b._begin_crop(image, {'cardId': b.current['characterId'], 'media_path': '', 'time': 0, 'crop': [0, 0, 1, 1]})
        QTest.qWait(80)
        js('portraitCropDialog.setRatio(1)')
        crop_dialog = w.findChild(QObject, 'portraitCropDialog')
        crop_rect = w.findChild(QObject, 'portraitCropRect')
        old_x = crop_dialog.property('cropX')
        center = crop_rect.mapToScene(QPointF(crop_rect.width()/2, crop_rect.height()/2)).toPoint()
        QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center)
        QTest.mouseMove(w, center + QPointF(20, 0).toPoint(), 20)
        QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, center + QPointF(20, 0).toPoint())
        assert crop_dialog.property('cropX') > old_x
        corner = next(item for item in crop_rect.childItems() if item.objectName() == 'portraitCorner3')
        old_width = crop_dialog.property('cropW')
        point = corner.mapToScene(QPointF(corner.width()/2, corner.height()/2)).toPoint()
        QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.mouseMove(w, point - QPointF(25, 25).toPoint(), 20)
        QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point - QPointF(25, 25).toPoint())
        assert crop_dialog.property('cropW') < old_width
        assert crop_dialog.property('cropW') * 320 / (crop_dialog.property('cropH') * 180) == pytest.approx(1)
        click('savePortraitCrop')
        assert b.currentPortraitUrl
        assert w.findChild(QObject, 'characterDialog').property('visible')
        # Render a real card with its embedded portrait; reject QML runtime failures.
        QTest.qWait(100)
        assert not w.grabWindow().isNull()
        errors = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'failed to load', 'Binding loop', 'Cannot assign', 'Unable to assign', 'Failed to get image', 'Duplicate method'))]
        assert not errors, errors
    finally:
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


def test_uncommitted_card_draft_is_recovered_and_committed_on_save(bridge, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    app, b = bridge
    cid = b.editor.document.characters[0].id
    b.selectCard(cid)
    b.stageCard(cid, 'Renamed', 'Alias', 'EXPORT', 'New description', 'Formal', 'Unfinished note')
    b.autosave()
    assert json.loads(b.recovery_path.read_text())['recovery_card_draft']['notes'] == 'Unfinished note'
    b._card_draft = {}
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    b.restore_recovery()
    assert b.currentCard['notes'] == 'Unfinished note'
    assert b.hasCardDraft and b.dirty
    b.save()
    assert not b.hasCardDraft and not b.dirty
    assert load_document(b.path).characters[0].name == 'Renamed'
    assert load_document(b.path).characters[0].notes == 'Unfinished note'


def test_save_as_ass_exports_without_leaving_project(bridge, monkeypatch, tmp_path):
    app, b = bridge
    original = b.path
    assert b.addReview('note', 'Project-only note', '')
    output = tmp_path / 'export.ass'
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *a: (str(output), 'ASS (*.ass)'))
    assert b.saveAs()
    assert b.path == original and b.isProject and b.dirty
    assert 'Project-only note' not in output.read_text()
    assert not output.with_name(output.name+'.substance').exists()
