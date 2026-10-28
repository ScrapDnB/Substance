import os
import sys
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import pytest
import shiboken6
from PySide6.QtCore import QObject, QEvent, Qt, QUrl
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QKeySequenceEdit
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import load_document
from substance.shortcuts import physical_character
from substance import visuals

ROOT = Path(__file__).resolve().parents[1]


def key_event(character, code, modifiers=Qt.ControlModifier, kind=QEvent.KeyPress, platform='cocoa'):
    return QKeyEvent(kind, ord(character.upper()), modifiers,
                     code if platform == 'windows' else 0,
                     code if platform == 'cocoa' else 0,
                     (1 << 20) if modifiers & Qt.ControlModifier else 0, character)


@pytest.mark.parametrize('platform,character,code,expected', [
    ('cocoa', 'ф', 0, 'A'), ('cocoa', 'а', 3, 'F'),
    ('cocoa', 'ё', 50, '`'), ('cocoa', '§', 50, '`'),
    ('windows', 'ф', 30, 'A'), ('windows', 'ё', 41, '`'),
    ('windows', 'а', 33, 'F'), ('windows', 'ф', 0x11e, None),
    ('offscreen', 'ф', 30, None),
])
def test_physical_keys(platform, character, code, expected):
    assert physical_character(key_event(character, code, platform=platform), platform) == expected


def test_missing_native_metadata_is_not_treated_as_mac_a():
    assert physical_character(QKeyEvent(QEvent.KeyPress, Qt.Key_F, Qt.ControlModifier), 'cocoa') is None


def test_other_layout_commands_typing_and_custom_shortcut(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle('Fusion')
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    # Synthetic events carry real macOS key codes, without changing the user's
    # input source or requiring a foreground native application.
    b.layout_shortcuts.platform = 'cocoa'
    b._set_document(load_document(ROOT / 'substance/resources/example.ass'), '')
    b.setMode('translation')
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
        assert engine.rootObjects()
        w = engine.rootObjects()[0]
        QTest.qWait(80)
        field = w.findChild(QObject, 'subtitleEditor')
        field.setProperty('text', 'Перевод')
        field.forceActiveFocus()
        def send(character, code, modifiers=Qt.ControlModifier, target=None):
            target = target or app.focusWindow()
            app.sendEvent(target, key_event(character, code, modifiers))
            app.sendEvent(target, key_event(character, code, modifiers, QEvent.KeyRelease))
            QTest.qWait(40)
        def close_dialog(target):
            target.requestActivate()
            QTest.qWait(100)
            if app.platformName() == 'cocoa' and not target.isActive():
                pytest.skip('Native window activation requires a foreground GUI session')
            if sys.platform == 'darwin':
                send('ц', 13, target=target)
            else:
                QTest.keyClick(app.focusWindow(), Qt.Key_Escape)
                QTest.qWait(40)
        send('ё', 50)
        dialog = w.findChild(QObject, 'assignCharacterDialog')
        assert dialog.isVisible()
        assert b.editor.document.cues[0].translation == 'Перевод'
        # Standard Close also follows its physical key in an auxiliary window.
        close_dialog(dialog)
        assert not dialog.isVisible() and w.isVisible()
        field.forceActiveFocus()
        field.selectAll()
        send('с', 8)
        assert app.clipboard().text() == 'Перевод'
        field.setProperty('text', '')
        send('ё', 50, Qt.NoModifier)
        send('а', 3, Qt.NoModifier)
        assert field.property('text') == 'ёа'
        send('а', 3)
        find = w.findChild(QObject, 'findDialog')
        assert find.isVisible()
        close_dialog(find)
        assert not find.isVisible()
        assert b.setShortcut('assignCharacter', 'Ctrl+K')
        send('л', 40)
        assert dialog.isVisible()
        close_dialog(dialog)
        assert not dialog.isVisible()
        # Identical command positions in other layouts do not run twice.
        before = b.count
        send('в', 2)
        assert b.count == before + 1
        # Structural edits use document history with a Russian layout too.
        field.forceActiveFocus()
        send('я', 6)
        assert b.count == before
        send('я', 6, Qt.ControlModifier | Qt.ShiftModifier)
        assert b.count == before + 1
        before = b.count
        send('х', 33, Qt.ControlModifier | Qt.ShiftModifier)
        assert b.count == before  # Unbound Ctrl+Shift+[ is untouched.
        assert not b.layout_shortcuts.eventFilter(w, key_event('х', 33, Qt.ControlModifier | Qt.ShiftModifier))
        assert not b.layout_shortcuts.eventFilter(w, key_event('у', 14, Qt.AltModifier))
    finally:
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        b.shutdown()


@pytest.mark.skipif(sys.platform != 'darwin', reason='AppKit path is macOS only')
def test_native_monitor_preserves_event_metadata_and_plain_text(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if app.platformName() != 'cocoa':
        pytest.skip('Run with QT_QPA_PLATFORM=cocoa')
    from AppKit import NSEvent, NSEventTypeKeyDown, NSEventModifierFlagCommand, NSEventModifierFlagShift
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    def event(text, code, flags):
        return NSEvent.keyEventWithType_location_modifierFlags_timestamp_windowNumber_context_characters_charactersIgnoringModifiers_isARepeat_keyCode_(
            NSEventTypeKeyDown, (12, 24), flags, 123.5, 0, None, text, text, True, code)
    try:
        translated = b.layout_shortcuts._native_event(event('ё', 50, NSEventModifierFlagCommand))
        assert translated.characters() == '`'
        assert translated.charactersIgnoringModifiers() == '`'
        assert translated.keyCode() == 50
        assert translated.timestamp() == 123.5 and translated.isARepeat()
        assert translated.modifierFlags() == NSEventModifierFlagCommand
        assert b.layout_shortcuts._native_event(event('а', 3, NSEventModifierFlagCommand)).characters() == 'f'
        assert b.layout_shortcuts._native_event(event('ы', 1, NSEventModifierFlagCommand | NSEventModifierFlagShift)).characters() == 'S'
        assert b.layout_shortcuts._native_event(event('ё', 50, 0)).characters() == 'ё'
        assert b.layout_shortcuts._native_event(event('у', 14, 0)).characters() == 'у'
    finally:
        b.shutdown()
    assert b.layout_shortcuts._monitor is None


def test_recording_shortcut_uses_physical_key(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    b.layout_shortcuts.platform = 'cocoa'
    recorder = QKeySequenceEdit()
    recorder.setMaximumSequenceLength(1)
    recorder.show()
    recorder.setFocus()
    QTest.qWait(40)
    try:
        app.sendEvent(recorder, key_event('к', 15))
        app.sendEvent(recorder, key_event('к', 15, kind=QEvent.KeyRelease))
        assert recorder.keySequence().toString() == 'Ctrl+R'
    finally:
        recorder.close()
        shiboken6.delete(recorder)
        b.shutdown()
