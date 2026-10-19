"""Preparation/Post use the real tool controls in the current document window."""
import os
from copy import deepcopy
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPointF, QMetaObject, Qt
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest

from test_workflow_ui import workflow_ui  # noqa: F401


def invoke(item, method='click'):
    assert item is not None
    assert QMetaObject.invokeMethod(item, method)
    QTest.qWait(30)


def within(item, ancestor):
    while item is not None:
        if item == ancestor:
            return True
        item = item.parentItem()
    return False


def visual_find(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = visual_find(child, name)
        if found is not None:
            return found
    return None


def select_tool(b, w, section, key):
    assert b.setSection(section)
    QTest.qWait(20)
    invoke(visual_find(w.contentItem(), section + 'Tool_' + key))
    page = w.findChild(QObject, section + 'Workspace')
    assert page.property('hasTool')
    tool = page.property('activeTool')
    assert not tool.property('visible')
    assert tool.property('embeddedActive')
    assert within(tool.property('dialogBody'), w.contentItem())
    assert within(tool.property('footer'), w.contentItem())
    assert page.property('activeKey') == key
    return tool


@pytest.mark.parametrize('section,keys', [
    ('preparation', ['files', 'transcription', 'hardsub', 'bitmap', 'forced', 'scenes', 'frames', 'compare', 'characters', 'portraits', 'settings']),
    ('post', ['checks', 'spelling', 'balance', 'retime', 'align', 'points', 'shift', 'compare', 'tags', 'delivery', 'batch']),
])
def test_all_tools_embed_body_and_footer_in_the_section(workflow_ui, section, keys):
    b, w, messages = workflow_ui
    assert b._save_path(str(b.data_dir / 'Section test.substance'))
    before = deepcopy(b.editor.document)
    for key in keys:
        tool = select_tool(b, w, section, key)
        assert tool.property('dialogBody').property('visible')
        assert not w.property('modalOpen')
    assert b.editor.document == before
    assert not [m for m in messages if any(s in m for s in (
        'ReferenceError', 'TypeError', 'Cannot assign', 'Unable to assign', 'Binding loop', 'is not a function'))], messages


def test_section_switch_preserves_translation_draft_selection_and_undo(workflow_ui):
    b, w, _ = workflow_ui
    b.setMode('translation')
    original = b.editor.document.cues[0].original
    b.stage('text', 'Перевод для выпуска')
    assert b.setSection('post')
    assert b.mode == 'translation'
    assert b.editor.document.cues[0].translation == 'Перевод для выпуска'
    assert b.editor.document.cues[0].original == original
    assert b.currentIndex == 0 and b.selection == {0}
    b.undo()
    assert b.editor.document.cues[0].translation is None
    b.setMode('timing')
    assert b.section == 'timing'
    assert not w.findChild(QObject, 'postWorkspace').property('visible')


def test_invalid_pending_time_rejects_all_section_changes(workflow_ui, monkeypatch):
    b, w, _ = workflow_ui
    errors = []
    monkeypatch.setattr(b, 'show_error', errors.append)
    b.stage('start', '00:00:09.000')
    for section in ('preparation', 'translation', 'post'):
        assert not b.setSection(section)
        assert b.section == b.mode == 'timing'
        assert w.findChild(QObject, 'workspaceSectionTabs').property('selectedIndex') == 1
    assert errors
    assert not b.setSection('invalid')


def test_embedded_checks_repair_and_undo_and_return_to_native_window(workflow_ui):
    b, w, messages = workflow_ui
    b.editor.update(0, text='Hello  world !')
    before = deepcopy(b.editor.document)
    tool = select_tool(b, w, 'post', 'checks')
    invoke(tool.findChild(QObject, 'analyzeToolsButton'))
    assert b.tools.canApply
    invoke(tool.findChild(QObject, 'applyToolsButton'))
    assert b.editor.document.cues[0].text == 'Hello world!'
    b.undo()
    assert b.editor.document == before
    b.setMode('timing')
    b.openChecks()
    assert tool.property('visible')
    assert tool.property('embeddedHost') is None
    assert not within(tool.property('dialogBody'), w.contentItem())
    assert not within(tool.property('footer'), w.contentItem())
    tool.close()


def test_shared_tool_moves_between_sections_without_an_empty_stale_surface(workflow_ui):
    b, w, _ = workflow_ui
    first = select_tool(b, w, 'preparation', 'compare')
    assert first is select_tool(b, w, 'post', 'compare')
    assert not w.findChild(QObject, 'preparationWorkspace').property('hasTool')
    select_tool(b, w, 'preparation', 'files')
    assert w.findChild(QObject, 'postWorkspace').property('hasTool')
    b.setSection('post')
    invoke(first, 'dismiss')
    assert not w.findChild(QObject, 'postWorkspace').property('hasTool')
    assert not first.property('visible')


def test_left_column_mouse_click_and_custom_footers_return_to_native_windows(workflow_ui):
    b, w, _ = workflow_ui
    b.setSection('post')
    QTest.qWait(30)
    button = visual_find(w.contentItem(), 'postTool_checks')
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)
    assert w.findChild(QObject, 'postWorkspace').property('hasTool')
    assert not w.findChild(QObject, 'editorToolsDialog').property('visible')
    for section, key, launch in [('preparation', 'transcription', b.openTranscription),
                                 ('post', 'align', b.openAlignment), ('post', 'shift', b.openShift)]:
        tool = select_tool(b, w, section, key)
        b.setMode('timing')
        launch()
        QTest.qWait(30)
        assert tool.property('visible')
        assert not within(tool.property('dialogBody'), w.contentItem())
        assert not within(tool.property('footer'), w.contentItem())
        assert tool.property('footer').width() == tool.width()
        tool.close()


@pytest.mark.parametrize('section', ['preparation', 'post'])
def test_recovery_restores_section_and_translation_mode(workflow_ui, monkeypatch, section):
    from PySide6.QtWidgets import QMessageBox
    b, _, _ = workflow_ui
    b.setMode('translation')
    b.stage('text', 'Перевод до восстановления')
    assert b.setSection(section)
    b.autosave()
    b.setMode('timing')
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    b.restore_recovery()
    assert b.section == section
    assert b.mode == 'translation'
    assert b.editor.document.cues[0].translation == 'Перевод до восстановления'


def test_embedded_tool_and_left_column_fit_small_window_and_large_scale(workflow_ui):
    b, w, messages = workflow_ui
    b.appearance.setValue('general', 'uiScale', 125)
    w.resize(980, 650)
    for section, key, action in [('preparation', 'transcription', 'speechStartButton'), ('post', 'align', 'alignmentApply')]:
        tool = select_tool(b, w, section, key)
        column = w.findChild(QObject, section + 'ToolColumn')
        position = column.mapToScene(QPointF())
        assert position.x() == 0
        assert position.x() + column.width() <= w.width() + 1
        assert not w.findChild(QObject, 'sidebarPane').property('visible')
        host = tool.property('embeddedHost')
        button = tool.findChild(QObject, action)
        pos = button.mapToItem(host, QPointF())
        assert pos.x() >= 0 and pos.y() >= 0
        assert pos.x() + button.width() <= host.width() + 1
        assert pos.y() + button.height() <= host.height() + 1
    assert not [m for m in messages if 'Binding loop' in m], messages


def test_empty_preparation_and_screenshots(workflow_ui):
    b, w, _ = workflow_ui
    b.newDocument()
    select_tool(b, w, 'preparation', 'files')
    assert w.findChild(QObject, 'preparationOpenFile').property('visible')
    assert b.count == 0
    folder = os.environ.get('SUBSTANCE_SECTIONS_SCREENSHOTS')
    if folder:
        def capture(name):
            expression = QQmlExpression(qmlContext(w), w, 'notification.close()')
            expression.evaluate()
            QTest.qWait(150)
            assert not expression.hasError()
            assert w.grabWindow().save(str(output / name))
        output = Path(folder)
        output.mkdir(parents=True, exist_ok=True)
        capture('preparation-files.png')
        b.openExample()
        select_tool(b, w, 'preparation', 'transcription')
        capture('preparation-transcription.png')
        select_tool(b, w, 'post', 'checks')
        invoke(w.findChild(QObject, 'editorToolsDialog').findChild(QObject, 'analyzeToolsButton'))
        capture('post-checks.png')
        select_tool(b, w, 'post', 'delivery')
        capture('post-delivery.png')
