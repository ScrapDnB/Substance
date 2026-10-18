from copy import deepcopy
from pathlib import Path

import shiboken6
from PySide6.QtCore import QObject, QPointF, QSize, QUrl, Qt, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.images import ProjectImageProvider
from substance.macos import MacOSIntegration
from substance import visuals  # noqa: F401
from test_portraits_controller import bridge, ready, wait_save


def click(window, item):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)


def visual_find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = visual_find(child, name)
        if found is not None:
            return found
    return None


def test_dialog_shows_results_and_applies_one_undo(bridge, qt_application):
    b = bridge
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    p = ready(b)
    before = deepcopy(b.editor.document)
    messages = []
    handler = qInstallMessageHandler(lambda kind, context, text: messages.append(text))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    try:
        assert engine.rootObjects(), messages
        root = engine.rootObjects()[0]
        dialog = root.findChild(QObject, 'autoPortraitsDialog')
        click(root, root.findChild(QObject, 'toolbarPortraits'))
        QTest.qWait(100)
        assert dialog.property('visible')
        assert dialog.findChild(QObject, 'portraitResults').property('count') == 2
        assert dialog.findChild(QObject, 'portraitModelsDirectory').property('text') == p.modelDirectory
        assert dialog.findChild(QObject, 'applyPortraitsButton').property('enabled')
        assert dialog.width() <= 1280
        assert dialog.property('hasPortrait')
        assert dialog.findChild(QObject, 'portraitCharacter').property('text') == 'Alice'
        click(dialog, dialog.findChild(QObject, 'applyPortraitsButton'))
        wait_save(p)
        assert dialog.findChild(QObject, 'portraitSaveProgressPanel').property('visible')
        assert dialog.findChild(QObject, 'portraitSaveProgress').property('value') == 1
        assert all(c.primary for c in b.editor.document.characters)
        b.undo()
        assert b.editor.document == before
        dialog.close()
    finally:
        for window in engine.rootObjects():
            window.hide()
            shiboken6.delete(window)
        shiboken6.delete(engine)
        qInstallMessageHandler(handler)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'is not a function', 'Non-existent'))], messages


def test_checkboxes_preserve_scroll_delegate_focus_and_window_geometry(bridge, qt_application):
    b = bridge
    QQuickStyle.setStyle('Fusion')
    p = ready(b)
    originals = p._rows
    p._rows = [{**originals[i % 2]} for i in range(40)]
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    try:
        root = engine.rootObjects()[0]
        b.openAutoPortraits()
        QTest.qWait(60)
        dialog = root.findChild(QObject, 'autoPortraitsDialog')
        results = dialog.findChild(QObject, 'portraitResults')
        results.setProperty('currentIndex', 20)
        results.setProperty('contentY', 20 * 112)
        QTest.qWait(60)
        row = visual_find(results, 'portraitRow20')
        checkbox = visual_find(results, 'portraitSelect20')
        assert row is not None and checkbox is not None
        geometry = dialog.x(), dialog.y(), dialog.width(), dialog.height()
        scroll = results.property('contentY')
        before = p._rows[20]['checked']
        for attempt in range(6):
            click(dialog, checkbox)
            assert p._rows[20]['checked'] == (not before if attempt % 2 == 0 else before)
            assert visual_find(results, 'portraitRow20') is row
            assert abs(results.property('contentY') - scroll) < 1
            assert results.property('currentIndex') == 20
            assert (dialog.x(), dialog.y(), dialog.width(), dialog.height()) == geometry
        assert p._rows[20]['checked'] == before
        assert dialog.findChild(QObject, 'portraitDetailSelect').property('checked') == before
        dialog.close()
    finally:
        for window in engine.rootObjects():
            window.hide()
            shiboken6.delete(window)
        shiboken6.delete(engine)


def test_native_toolbar_opens_portraits(bridge, monkeypatch):
    monkeypatch.setattr(MacOSIntegration, 'refresh_palette', lambda *args: None)
    native = MacOSIntegration(bridge)
    assert 'substance.portraits' in native.default_identifiers
    assert native.ACTIONS['substance.portraits'][2] == 'openAutoPortraits'
    from PySide6.QtTest import QSignalSpy
    opened = QSignalSpy(bridge.portraits.requested)
    native.perform('substance.portraits')
    assert opened.count() == 1


def test_character_autocomplete_filters_keyboard_mouse_and_preserves_unconfirmed_assignment(bridge, qt_application):
    from substance.project import CharacterCard
    from PySide6.QtGui import QInputMethodEvent
    b = bridge
    QQuickStyle.setStyle('Fusion')
    b.editor.document.characters += [CharacterCard(id=f'extra-{i}', name=f'Character {i:03}') for i in range(200)]
    b.editor.document.characters += [CharacterCard(id='anna', name='Анна'), CharacterCard(id='joanna', name='Жоанна')]
    b.changed.emit()
    p = ready(b)
    p._rows = p._rows[:2]
    p._rows[0]['cardId'] = ''
    p._rows[0]['checked'] = False
    p.setShowUnnamed(True)
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    try:
        root = engine.rootObjects()[0]
        b.openAutoPortraits()
        QTest.qWait(60)
        dialog = root.findChild(QObject, 'autoPortraitsDialog')
        field = dialog.findChild(QObject, 'portraitCharacter')
        results = dialog.findChild(QObject, 'portraitResults')
        popup = field.findChild(QObject, 'portraitCharacterSuggestions')
        matches = field.findChild(QObject, 'portraitCharacterMatches')
        geometry = dialog.x(), dialog.y(), dialog.width(), dialog.height()
        click(dialog, field)
        event = QInputMethodEvent()
        event.setCommitString('АНН')
        qt_application.sendEvent(field, event)
        QTest.qWait(60)
        assert popup.property('opened') and matches.property('count') == 3
        assert field.property('activeFocus') and p._rows[0]['cardId'] == ''
        QTest.keyClick(dialog, Qt.Key.Key_Down)
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        QTest.qWait(40)
        assert p._rows[0]['cardId'] == 'joanna' and p._rows[0]['checked']
        assert field.property('text') == 'Жоанна' and not popup.property('opened')
        def type_text(text):
            field.selectAll()
            edit = QInputMethodEvent()
            edit.setCommitString(text)
            qt_application.sendEvent(field, edit)
        type_text('does-not-exist')
        assert matches.property('count') == 1
        assert p._rows[0]['cardId'] == 'joanna'
        QTest.keyClick(dialog, Qt.Key.Key_Escape)
        assert dialog.property('visible') and field.property('text') == 'Жоанна'
        type_text('ctER 157')
        QTest.qWait(60)
        assert matches.property('count') == 2
        click(dialog, matches.property('currentItem'))
        assert p._rows[0]['cardId'] == 'extra-157'
        results.setProperty('currentIndex', 1)
        QTest.qWait(30)
        assert field.property('text') == 'Bob'
        results.setProperty('currentIndex', 0)
        click(dialog, field)
        type_text('Alice')
        click(dialog, dialog.findChild(QObject, 'portraitDetailSelect'))
        assert p._rows[0]['cardId'] == 'extra-157' and field.property('text') == 'Character 157'
        click(dialog, field.findChild(QObject, 'portraitCharacterClear'))
        assert p._rows[0]['cardId'] == '' and not p._rows[0]['checked']
        click(dialog, field)
        type_text('New Hero')
        QTest.qWait(40)
        assert matches.property('count') == 1
        QTest.keyClick(dialog, Qt.Key.Key_Return)
        QTest.qWait(40)
        assert p.rows[0]['newCharacter'] and field.property('text') == 'New Hero'
        assert not any(c.name == 'New Hero' for c in b.editor.document.characters)
        click(dialog, dialog.findChild(QObject, 'applyPortraitsButton'))
        wait_save(p)
        assert next(c for c in b.editor.document.characters if c.name == 'New Hero').primary
        assert (dialog.x(), dialog.y(), dialog.width(), dialog.height()) == geometry
        dialog.close()
    finally:
        for window in engine.rootObjects():
            window.hide()
            shiboken6.delete(window)
        shiboken6.delete(engine)


def test_filter_checkbox_targets_correct_source_row_at_narrow_width(bridge, qt_application, tmp_path):
    b = bridge
    QQuickStyle.setStyle('Fusion')
    p = ready(b)
    p._rows.insert(0, {**p._rows[0], 'cardId': '', 'checked': False})
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.addImageProvider('project', ProjectImageProvider(b))
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    try:
        root = engine.rootObjects()[0]
        b.openAutoPortraits()
        QTest.qWait(60)
        dialog = root.findChild(QObject, 'autoPortraitsDialog')
        dialog.setMinimumSize(QSize(752, 650))
        dialog.resize(752, 720)
        QTest.qWait(60)
        results = dialog.findChild(QObject, 'portraitResults')
        assert results.property('count') == 2
        assert dialog.findChild(QObject, 'portraitSpeed').property('currentIndex') == 1
        click(dialog, visual_find(results, 'portraitSelect0'))
        assert not p._rows[1]['checked'] and p._rows[2]['checked']
        toggle = dialog.findChild(QObject, 'portraitShowUnnamed')
        click(dialog, toggle)
        assert p.showUnnamed and results.property('count') == 3
        results.setProperty('currentIndex', 0)
        click(dialog, toggle)
        assert not p.showUnnamed and results.property('count') == 2
        assert dialog.property('selectedPortrait')['sourceIndex'] == 1
        click(dialog, dialog.findChild(QObject, 'applyPortraitsButton'))
        wait_save(p)
        QTest.qWait(60)
        assert p.saveProgress == 1
        assert not b.editor.document.characters[0].primary
        assert b.editor.document.characters[1].primary
        for name in ('portraitSpeed', 'applyPortraitsButton', 'portraitSaveProgress', 'portraitDetailSelect'):
            item = dialog.findChild(QObject, name)
            position = item.mapToScene(QPointF(0, 0))
            assert item.isVisible() and position.x() >= 0 and position.y() >= 0
            assert position.x() + item.width() <= dialog.width() + 1
            assert position.y() + item.height() <= dialog.height() + 1
        assert dialog.grabWindow().save(str(tmp_path / 'portraits-narrow-saved.png'))
        p._speed = 'fast'
        p.changed.emit()
        dialog.resize(752, 650)
        QTest.qWait(60)
        button = dialog.findChild(QObject, 'applyPortraitsButton')
        assert button.mapToScene(QPointF(0, 0)).y() + button.height() <= dialog.height()
        assert dialog.grabWindow().save(str(tmp_path / 'portraits-fast-small.png'))
        dialog.close()
    finally:
        for window in engine.rootObjects():
            window.hide()
            shiboken6.delete(window)
        shiboken6.delete(engine)
