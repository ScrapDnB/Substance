import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, Qt, QPointF, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import load_document
from substance import visuals

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Fusion")
    return instance


@pytest.fixture
def backend(app, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    bridge = Backend()
    bridge._set_document(load_document(ROOT / "substance/resources/example.ass"), "")
    yield bridge
    bridge.shutdown()


def test_selection_filters_and_merge_follow_result(backend):
    assert backend.select(0, 0)
    assert backend.select(1, Qt.KeyboardModifier.ShiftModifier.value)
    assert backend.selection == {0, 1}
    backend.mergeLines()
    assert backend.selection == {0}
    assert backend.currentIndex == 0
    assert backend.count == 7
    backend.deleteLines()
    assert backend.selection == {0}
    assert backend.count == 6
    backend.setSearch('tickets', False, False)
    assert backend.visibleCount == 1
    assert backend.setSearch('(', False, True) is False
    assert backend.visibleCount == 1


def test_pending_draft_committed_before_navigation(backend):
    backend.setMode('translation')
    original = backend.editor.document.cues[0].original
    backend.stage('text', 'Ты всё-таки пришёл.')
    assert backend.dirty
    backend.navigate(1)
    assert backend.editor.document.cues[0].translation == 'Ты всё-таки пришёл.'
    assert backend.editor.document.cues[0].original == original
    backend.undo()
    assert backend.editor.document.cues[0].translation is None


def test_invalid_time_prevents_navigation_and_save(backend, tmp_path):
    backend.stage('start', '00:00:09.000')
    assert not backend.select(1, 0)
    assert backend.currentIndex == 0
    backend.path = str(tmp_path / 'invalid.ass')
    assert not backend.save()
    assert not Path(backend.path).exists()
    assert backend.editor.document.cues[0].start == 1000


def test_autosave_contains_uncommitted_input(backend):
    backend.stage('text', 'Unsaved draft')
    backend.autosave()
    import json
    saved = json.loads(backend.recovery_path.read_text())
    assert saved['recovery_draft']['text'] == 'Unsaved draft'


def test_recovery_restores_visible_draft_mode_and_selection(backend, monkeypatch):
    backend.setMode('translation')
    backend.select(3, 0)
    backend.stage('text', 'Незавершённый\nперевод')
    backend.stage('start', 'ещё ввожу время')
    backend.autosave()
    backend.draft.clear()
    backend._mode = 'timing'
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    backend.restore_recovery()
    assert backend.mode == 'translation'
    assert backend.currentIndex == 3
    assert backend.selection == {3}
    assert backend.current['editText'] == 'Незавершённый\nперевод'
    assert backend.current['startTime'] == 'ещё ввожу время'
    assert not backend.flush()
    assert backend.dirty
    assert not any(k.startswith('recovery_') for k in backend.editor.document.to_dict())


def test_regex_replace_reports_error_without_mutation(backend):
    before = backend.editor.document.ass_text()
    backend.replace('(', 'x', True, True, False)
    assert backend.editor.document.ass_text() == before
    assert not backend.canUndo


def test_spelling_results_are_rejected_after_an_edit(backend):
    backend._spelling_revision = (id(backend.editor), backend.editor.revision)
    backend.editor.update(0, text='A changed sentence')
    backend._spelling_done([{'index': 0, 'word': 'helllo', 'suggestions': ['hello']}])
    assert backend.spellingResults == []
    backend.correctSpelling(0, 'changed', 'old')
    assert backend.editor.document.cues[0].text == 'A changed sentence'


def test_qml_typing_keyboard_navigation_and_modes(app, backend):
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
        assert engine.rootObjects(), messages
        window = engine.rootObjects()[0]
        QTest.qWait(100)
        field = window.findChild(QObject, 'subtitleEditor')
        assert field is not None
        field.setProperty('text', 'Hello world')
        field.setProperty('cursorPosition', 5)
        QTest.qWait(650)
        assert backend.editor.document.cues[0].text == 'Hello world'
        assert field.property('cursorPosition') == 5
        backend.setMode('translation')
        QTest.qWait(100)
        field = window.findChild(QObject, 'subtitleEditor')
        field.setProperty('text', 'Привет, мир!')
        field.forceActiveFocus()
        QTest.keyClick(window, Qt.Key.Key_Return, Qt.KeyboardModifier.ControlModifier)
        QTest.qWait(100)
        assert backend.currentIndex == 1
        assert backend.editor.document.cues[0].translation == 'Привет, мир!'
        assert backend.editor.document.cues[0].status == 'done'
        backend.setMode('timing')
        backend.select(0, 0)
        QTest.qWait(100)
        wave = window.findChild(QObject, 'audioWaveform')
        assert wave is not None
        selector = window.findChild(QObject, 'audioDisplaySelector')
        spectrum = selector.mapToScene(QPointF(selector.width() * .75, selector.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, spectrum)
        assert wave.spectral and selector.property('currentIndex') == 1
        QTest.keyClick(window, Qt.Key.Key_Left)
        assert not wave.spectral and selector.property('currentIndex') == 0
        QTest.keyClick(window, Qt.Key.Key_Right)
        assert wave.spectral and selector.property('currentIndex') == 1
        waveform = selector.mapToScene(QPointF(selector.width() * .25, selector.height() / 2)).toPoint()
        QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, waveform)
        assert not wave.spectral and selector.property('currentIndex') == 0
        wave.rangeRequested.emit(1200, 3400)
        assert backend.editor.document.cues[0].start == 1200
        assert backend.editor.document.cues[0].end == 3400
        wave.setProperty('snap', False)
        begin = wave.mapToScene(QPointF(wave._x(wave.start), wave.height() / 2)).toPoint()
        finish = begin + QPointF(50, 0).toPoint()
        previous_start = wave.start
        QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, begin)
        QTest.mouseMove(window, finish, 20)
        QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, finish)
        QTest.qWait(50)
        assert backend.editor.document.cues[0].start > previous_start
        assert backend.editor.document.cues[0].end == 3400
        errors = [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'failed to load', 'Binding loop', 'Cannot assign'))]
        assert not errors, errors
    finally:
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


def test_created_text_becomes_original_until_first_translation():
    from substance.editor import Editor
    editor = Editor()
    editor.add()
    editor.update(0, text='First draft')
    editor.update(0, text='Final original')
    assert editor.document.cues[0].original == 'Final original'
    editor.update(0, translation='Перевод')
    assert editor.document.cues[0].original == 'Final original'
    editor.split(0, 3, 1000, translation_mode=True)
    editor.merge([0, 1])
    assert editor.document.cues[0].original == 'Final original'
