from copy import deepcopy
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, QUrl, Qt, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import Cue, Document
from substance import visuals  # noqa: F401


@pytest.fixture
def ui(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    b = Backend()
    doc = Document()
    for i in range(6):
        cue = Cue(start=1000 + 10000 * i, end=3000 + 10000 * i, text='Реплика ' + str(i + 1))
        doc.register_source(cue)
        doc.cues.append(cue)
    b._set_document(doc, '')
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    w = engine.rootObjects()[0]
    QTest.qWait(80)
    yield b, w
    b.shutdown()
    w.hide()
    shiboken6.delete(w)
    shiboken6.delete(engine)
    qInstallMessageHandler(previous)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'is not a function', 'Non-existent', 'Could not attach'))], messages


def click(w, obj):
    pos = obj.mapToScene(QPointF(obj.width() / 2, obj.height() / 2)).toPoint()
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
    QTest.qWait(30)


def js(w, code):
    exp = QQmlExpression(qmlContext(w), w, code)
    exp.evaluate()
    assert not exp.hasError(), exp.error().toString()
    QTest.qWait(30)


def test_visible_shift_live_preview_cancel_apply_one_undo(ui):
    b, w = ui
    before = deepcopy(b.editor.document)
    click(w, w.findChild(QObject, 'toolbarShift'))
    d = w.findChild(QObject, 'shiftDialog')
    assert d.isVisible() and d.transientParent() == w
    amount = d.findChild(QObject, 'shiftAmount')
    amount.setProperty('value', 500)
    assert b.timing.delta == 500 and b.timing.changedCount == 6
    assert b.editor.document == before
    assert d.findChild(QObject, 'applyTimingButton').property('enabled')
    d.reject()
    assert b.editor.document == before
    b.openShift()
    amount.setProperty('value', 1000)
    js(d, 'directionIndex = 0; updateShift()')
    assert b.timing.delta == -1000
    click(d, d.findChild(QObject, 'applyTimingButton'))
    assert not d.isVisible()
    assert b.editor.document.cues[0].start == 0
    b.undo()
    assert b.editor.document == before


def test_points_manual_target_pending_apply_validation_and_small_layout(ui, tmp_path):
    b, w = ui
    before = deepcopy(b.editor.document)
    click(w, w.findChild(QObject, 'toolbarPointSync'))
    d = w.findChild(QObject, 'shiftDialog')
    assert d.isVisible() and d.property('pointMode')
    assert not d.findChild(QObject, 'pointFromPlayer').property('enabled')
    target = d.findChild(QObject, 'pointTargetTime')
    js(d, 'editTarget("00:00:02.000")')
    assert not d.findChild(QObject, 'applyTimingButton').property('enabled')
    click(d, d.findChild(QObject, 'setSyncPoint'))
    assert len(b.timing.points) == 1 and b.timing.canApply
    assert d.findChild(QObject, 'syncPointsList').property('count') == 1
    assert d.findChild(QObject, 'applyTimingButton').property('enabled')
    b.timing.selectPreview(5)
    js(d, 'editTarget("00:01:02.000")')
    assert d.findChild(QObject, 'timingPreviewList').property('currentIndex') == 5
    click(d, d.findChild(QObject, 'setSyncPoint'))
    assert b.timing.preview['start'] == 62000
    assert b.editor.document == before
    d.resize(800, 660)
    QTest.qWait(80)
    for name in ('setSyncPoint', 'applyTimingButton', 'timingPreviewList'):
        obj = d.findChild(QObject, name)
        point = obj.mapToScene(QPointF(0, 0))
        assert point.x() >= 0 and point.y() >= 0
        assert point.x() + obj.width() <= d.width() + 1
        assert point.y() + obj.height() <= d.height() + 1
    assert d.grabWindow().save(str(tmp_path / 'points.png'))
    click(d, d.findChild(QObject, 'applyTimingButton'))
    assert not d.isVisible() and b.editor.document.cues[5].start == 62000
    b.undo()
    assert b.editor.document == before


def test_shift_invalid_and_stale_stay_open(ui):
    b, w = ui
    b.openShift()
    d = w.findChild(QObject, 'shiftDialog')
    d.findChild(QObject, 'shiftAmount').setProperty('value', 5000)
    js(d, 'directionIndex = 0; updateShift()')
    assert not d.findChild(QObject, 'applyTimingButton').property('enabled')
    assert 'раньше нуля' in d.findChild(QObject, 'timingStatus').property('text')
    js(d, 'directionIndex = 1; updateShift()')
    b.editor.update(0, text='Обновление')
    b._refresh()
    assert not d.findChild(QObject, 'applyTimingButton').property('enabled')
    assert 'Документ изменился' in d.findChild(QObject, 'timingStatus').property('text')
    d.reject()


def test_edit_and_tools_menus_have_separate_commands(ui):
    _, w = ui
    import json

    def texts(menu):
        code = 'JSON.stringify(Array.from({length: ' + menu + '.count}, (_, i) => ' + menu + '.itemAt(i).text || ""))'
        exp = QQmlExpression(qmlContext(w), w, code)
        value = exp.evaluate()
        assert not exp.hasError(), exp.error().toString()
        return json.loads(value[0] if isinstance(value, tuple) else value)

    edit = texts('editMenu')
    tools = texts('toolsMenu')
    assert 'Отменить' in edit and 'Найти…' in edit and 'Скопировать реплики' in edit
    groups = {
        'qualityMenu': ('Проверить и исправить…', 'Проверить орфографию…'),
        'cuesMenu': ('Переносы и разбиение…',),
        'mediaMenu': ('Найти и распознать хардсаб…', 'Создать субтитры из аудио…'),
        'timingMenu': ('Уточнить по речи…', 'Обработать интервалы…', 'Тайминг готового сценария…'),
        'toolsMenu': ('Автопортреты из видео…', 'Персонажи проекта…'),
    }
    for menu, titles in groups.items():
        for title in titles:
            assert title in texts(menu) and title not in edit
    assert 'Проверить и исправить…' not in tools


def test_point_sync_explains_pending_time_and_guides_review(ui):
    b, w = ui
    b.openPointSync()
    d = w.findChild(QObject, 'shiftDialog')
    QTest.qWait(40)
    assert 'правильным временем' in d.findChild(QObject, 'timingIntroduction').property('text')
    assert 'Одна точка' in d.findChild(QObject, 'timingStatus').property('text')
    assert '00:00:01.000' in d.findChild(QObject, 'pointOriginalTime').property('text')
    review = d.findChild(QObject, 'timingReviewButton')
    assert not review.property('enabled')
    js(d, 'editTarget("00:00:02.000")')
    assert 'ещё не учтено' in d.findChild(QObject, 'pointEntryStatus').property('text')
    click(d, d.findChild(QObject, 'setSyncPoint'))
    assert review.property('enabled')
    assert 'Точка добавлена' in d.findChild(QObject, 'pointEntryStatus').property('text')
    assert 'Одна точка' in d.findChild(QObject, 'pointMappingExplanation').property('text')
    assert '+1,000' in d.findChild(QObject, 'pointMappingExplanation').property('text') or '+1.000' in d.findChild(QObject, 'pointMappingExplanation').property('text')
    click(d, review)
    scroll = d.findChild(QObject, 'timingDetailScroll')
    result = d.findChild(QObject, 'timingResultCard')
    assert scroll.property('contentItem').property('contentY') > 0
    assert result.mapToScene(QPointF(0, 0)).y() < d.height() - 100
    assert '00:00:02.000' in d.findChild(QObject, 'timingAfterResult').property('text')
    # A different cue returns to step 2 and loads its original time, not the
    # shifted preview, so adding another anchor cannot accidentally double it.
    b.timing.selectPreview(5)
    QTest.qWait(40)
    assert scroll.property('contentItem').property('contentY') == 0
    assert d.findChild(QObject, 'pointTargetTime').property('text') == '00:00:51.000'
    js(d, 'editTarget("00:01:02.000")')
    assert not review.property('enabled')
    click(d, d.findChild(QObject, 'setSyncPoint'))
    assert 'Точек: 2' in d.findChild(QObject, 'pointMappingExplanation').property('text')
    assert '00:01:02.000' in d.findChild(QObject, 'timingAfterResult').property('text')
    assert b.editor.document.cues[5].start == 51000
    d.reject()


def test_point_sync_player_capture_and_small_window_review(ui, monkeypatch):
    b, w = ui
    # Exercise the media-dependent controls with a deterministic player position.
    b.media_controller.path = 'preview.wav'
    monkeypatch.setattr(b.media_controller.player, 'position', lambda: 2000)
    b.media_controller.changed.emit()
    b.media_controller.positionChanged.emit()
    played = []
    monkeypatch.setattr(b.media_controller, 'playRange', lambda *args: played.append(args))
    b.openPointSync()
    d = w.findChild(QObject, 'shiftDialog')
    d.resize(800, 660)
    QTest.qWait(60)
    capture = d.findChild(QObject, 'pointFromPlayer')
    assert capture.property('enabled')
    click(d, capture)
    assert d.findChild(QObject, 'pointTargetTime').property('text') == '00:00:02.000'
    for name in ('pointFromPlayer', 'setSyncPoint', 'timingReviewButton', 'applyTimingButton'):
        item = d.findChild(QObject, name)
        position = item.mapToScene(QPointF(0, 0))
        assert 0 <= position.x() <= d.width() - item.width() + 1
        assert 0 <= position.y() <= d.height() - item.height() + 1
    click(d, d.findChild(QObject, 'setSyncPoint'))
    click(d, d.findChild(QObject, 'timingReviewButton'))
    click(d, d.findChild(QObject, 'timingPlayBefore'))
    click(d, d.findChild(QObject, 'timingPlayAfter'))
    assert played == [(1000, 3000), (2000, 4000)]
    d.reject()
