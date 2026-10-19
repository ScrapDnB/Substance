import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QEvent, QSettings, Qt, QUrl, qInstallMessageHandler
from PySide6.QtGui import QKeyEvent, QKeySequence
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from substance import visuals  # noqa: F401
from substance.backend import Backend
from substance.document import Cue, Document
from substance.shortcuts import TIMING_NUDGES, timing_shortcut_defaults


@pytest.fixture
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    doc = Document(cues=[Cue(start=1000, end=3000, text='Первая реплика'),
                         Cue(start=4000, end=5000, text='Вторая реплика')])
    b._set_document(doc, '')
    yield b
    b.shutdown()


@pytest.fixture
def ui(backend):
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    w = engine.rootObjects()[0]
    w.requestActivate()
    QTest.qWait(80)
    try:
        yield backend, w
    finally:
        w.hide()
        shiboken6.delete(w)
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign'))], messages


def press(w, sequence):
    combination = QKeySequence(sequence)[0]
    QTest.keyClick(w, combination.key(), combination.keyboardModifiers())
    QTest.qWait(20)


def find_visual(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = find_visual(child, name)
        if found is not None:
            return found


@pytest.mark.parametrize('platform,start,end', [('darwin', 'Meta', 'Ctrl'), ('win32', 'Ctrl', 'Ctrl+Alt')])
def test_platform_modifiers(platform, start, end):
    defaults = timing_shortcut_defaults(platform)
    assert defaults['nudgeStartBack'] == start + '+Left'
    assert defaults['nudgeEndForwardFine'] == end + '+Shift+Right'
    assert defaults['nudgeBothBack'] == 'Alt+Left'
    assert len(set(defaults.values())) == 12


@pytest.mark.parametrize('action', list(TIMING_NUDGES))
@pytest.mark.parametrize('focus', ['subtitleEditor', 'startField', None])
def test_keys_move_only_current_cue_from_editor_and_workspace(ui, action, focus):
    b, w = ui
    # Multiple selection must not turn a current-cue shortcut into a batch edit.
    b.selection = {0, 1}
    other = deepcopy(b.editor.document.cues[1])
    item = w.findChild(QObject, focus) if focus else w.contentItem()
    item.forceActiveFocus()
    QTest.qWait(10)
    press(w, b.shortcuts[action])
    edge, direction, fine = TIMING_NUDGES[action]
    delta = direction * (10 if fine else 100)
    cue = b.editor.document.cues[0]
    assert (cue.start, cue.end) == (1000 + (delta if edge != 'end' else 0),
                                    3000 + (delta if edge != 'start' else 0))
    assert b.editor.document.cues[1] == other
    assert len(b.editor.undo_stack) == 1
    b.undo()
    assert (b.current['start'], b.current['end']) == (1000, 3000)
    b.redo()
    assert (b.current['start'], b.current['end']) == (cue.start, cue.end)


def test_draft_repeat_custom_binding_and_plain_arrows(ui):
    b, w = ui
    field = w.findChild(QObject, 'subtitleEditor')
    field.forceActiveFocus()
    for key in 'draft':
        QTest.keyClick(w, key)
    assert b.draft
    press(w, b.shortcuts['nudgeBothForward'])
    assert b.editor.document.cues[0].output_text.startswith('draft')
    assert not b.draft
    assert b.current['start'] == 1100
    text = field.property('text')
    cursor = field.property('cursorPosition')
    press(w, 'Left')
    assert b.current['start'] == 1100
    assert field.property('cursorPosition') == max(0, cursor - 1)
    assert field.property('text') == text
    assert b.setShortcut('nudgeBothForward', 'Ctrl+K')
    press(w, 'Alt+Right')
    assert b.current['start'] == 1100
    press(w, 'Ctrl+K')
    assert b.current['start'] == 1200
    combo = QKeySequence('Ctrl+K')[0]
    QApplication.sendEvent(w, QKeyEvent(QEvent.KeyPress, combo.key(), combo.keyboardModifiers(), '', True))
    assert b.current['start'] == 1300
    assert not b.setShortcut('nudgeStartBack', 'Ctrl+K')
    assert not b.setShortcut('nudgeStartBack', 'Ctrl+K, Ctrl+L')


def test_clamps_draft_validation_and_busy(backend):
    b = backend
    b.setTimingStep('step', 5000)
    b.nudgeTiming('both', -1, False)
    assert (b.current['start'], b.current['end']) == (0, 2000)
    b.nudgeTiming('both', -1, False)
    assert len(b.editor.undo_stack) == 1  # No empty undo at the boundary.
    b.undo()
    b.nudgeTiming('start', 1, False)
    assert (b.current['start'], b.current['end']) == (3000, 3000)
    b.undo()
    b.nudgeTiming('end', -1, False)
    assert (b.current['start'], b.current['end']) == (1000, 1000)
    b.undo()
    b.stage('start', 'invalid')
    b.nudgeTiming('both', 1, False)
    assert (b.current['start'], b.current['end']) == (1000, 3000)
    assert b.draft == {'start': 'invalid'}
    b.draft.clear()
    b._busy = True
    b.nudgeTiming('both', 1, False)
    assert b.current['start'] == 1000


def test_settings_controls_persist_and_dialog_blocks_timing(ui, tmp_path):
    b, w = ui
    d = w.findChild(QObject, 'settingsDialog')
    d.open()
    w.findChild(QObject, 'settingsNavigation').setProperty('page', 2)
    QTest.qWait(80)
    assert not w.property('timingShortcutsEnabled')
    step = find_visual(d.contentItem(), 'timing_step')
    assert step.property('value') == 100
    assert find_visual(d.contentItem(), 'timing_fineStep').property('value') == 10
    for action in TIMING_NUDGES:
        button = find_visual(d.contentItem(), 'timingShortcut_' + action)
        assert button and button.property('visible') and button.property('text')
    field = step.property('contentItem')
    field.forceActiveFocus()
    field.setProperty('text', '250')
    QTest.keyClick(d, Qt.Key_Return)
    QTest.qWait(30)
    assert b.timingSteps['step'] == 250
    b.setTimingStep('fineStep', 5)
    assert step.property('value') == 250
    assert b.setShortcut('nudgeStartBack', 'Ctrl+K')
    d.resize(880, 560)
    QTest.qWait(80)
    assert d.grabWindow().save(str(tmp_path / 'timing-settings.png'))
    before = deepcopy(b.editor.document)
    # Even a key sent to the main window cannot modify cues while settings is open.
    press(w, b.shortcuts['nudgeBothForward'])
    assert b.editor.document == before
    b.settings.sync()
    restored = Backend()
    try:
        assert restored.timingSteps == {'step': 250, 'fineStep': 5}
        assert restored.shortcuts['nudgeStartBack'] == 'Ctrl+K'
        restored.resetTimingControls()
        assert restored.timingSteps == {'step': 100, 'fineStep': 10}
        assert restored.shortcuts['nudgeStartBack'] == timing_shortcut_defaults(sys.platform)['nudgeStartBack']
    finally:
        restored.shutdown()
    d.reject()


def test_old_frame_bindings_migrate_custom_binding_survives(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    settings.setValue('shortcuts', json.dumps({'frameBack': 'Alt+Left', 'frameForward': 'Ctrl+9'}))
    settings.sync()
    b = Backend()
    try:
        assert b.shortcuts['frameBack'] == 'Alt+,'
        assert b.shortcuts['frameForward'] == 'Ctrl+9'
        assert len(set(b.shortcuts.values())) == len(b.shortcuts) - 1  # Existing add/apply alias.
    finally:
        b.shutdown()
