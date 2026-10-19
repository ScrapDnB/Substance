"""Column boundaries resize real table headers and rows without editing cues."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from substance.appearance import AppearanceSettings
from test_workflow_ui import workflow_ui  # noqa: F401


def drag(w, item, delta):
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(w, point + QPointF(delta, 0).toPoint(), 25)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point + QPointF(delta, 0).toPoint())
    QTest.qWait(25)


@pytest.mark.parametrize('mode,key,property_name', [
    ('timing', 'number', 'numberWidth'), ('timing', 'start', 'startWidth'),
    ('timing', 'end', 'endWidth'), ('timing', 'portrait', 'portraitWidth'),
    ('timing', 'actor', 'actorWidth'), ('timing', 'text', 'sourceWidth'),
    ('translation', 'original', 'sourceWidth'), ('translation', 'translation', 'translatedWidth'),
    ('translation', 'remarks', 'statusWidth'),
])
def test_dragging_column_boundaries_updates_widths_and_persists_per_mode(workflow_ui, mode, key, property_name):
    b, w, messages = workflow_ui
    b.appearance.setValue('general', 'sidebarVisible', False)
    b.setMode(mode)
    QTest.qWait(60)
    table = w.findChild(QObject, 'subtitleTablePanel')
    before = deepcopy(b.editor.document)
    selected = b.currentIndex, set(b.selection)
    width = table.property(property_name)
    handle = w.findChild(QObject, 'resizeColumn_' + key)
    assert handle is not None
    drag(w, handle, 35)
    assert table.property(property_name) == pytest.approx(width + 35, abs=1)
    assert b.appearance.columnWidths[mode][key] == pytest.approx(width + 35, abs=1)
    assert b.editor.document == before and not b.dirty
    assert (b.currentIndex, b.selection) == selected
    other = 'translation' if mode == 'timing' else 'timing'
    assert key not in b.appearance.columnWidths[other]
    b.settings.sync()
    restored = AppearanceSettings(b.settings)
    assert restored.columnWidths == b.appearance.columnWidths
    # Rows and headers continue to share the same rightmost cell.
    header = w.findChild(QObject, 'tableRemarksHeader')
    assert header.parentItem().childItems()[-1] == header
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Unable to assign'))], messages


def test_column_double_click_restores_automatic_width_and_scale_is_preserved(workflow_ui):
    b, w, _ = workflow_ui
    b.appearance.setValue('general', 'sidebarVisible', False)
    table = w.findChild(QObject, 'subtitleTablePanel')
    handle = w.findChild(QObject, 'resizeColumn_actor')
    QTest.qWait(40)
    automatic = table.property('actorWidth')
    drag(w, handle, 40)
    logical = b.appearance.columnWidths['timing']['actor']
    b.appearance.setValue('general', 'uiScale', 125)
    QTest.qWait(40)
    assert table.property('actorWidth') == pytest.approx(logical * 1.25)
    point = handle.mapToScene(QPointF(handle.width() / 2, handle.height() / 2)).toPoint()
    QTest.mouseDClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)
    assert 'actor' not in b.appearance.columnWidths['timing']
    assert table.property('actorWidth') == automatic


def test_invalid_column_widths_are_bounded_and_horizontal_overflow_is_scrollable(workflow_ui):
    b, w, _ = workflow_ui
    before = deepcopy(b.editor.document)
    b.appearance.setColumnWidth('timing', 'number', -100)
    assert b.appearance.columnWidths['timing']['number'] == 32
    for value in (float('nan'), float('inf')):
        b.appearance.setColumnWidth('timing', 'number', value)
    assert b.appearance.columnWidths['timing']['number'] == 32
    b.appearance.setColumnWidth('timing', 'text', 16000)
    assert b.appearance.columnWidths['timing']['text'] == 1600
    b.appearance.setColumnWidth('invalid', 'text', 300)
    b.appearance.setColumnWidth('timing', 'invalid', 300)
    w.resize(980, 650)
    QTest.qWait(40)
    viewport = w.findChild(QObject, 'tableHorizontalViewport')
    assert viewport.property('contentWidth') > viewport.width()
    header = w.findChild(QObject, 'tableRemarksHeader')
    right = header.mapToItem(viewport, QPointF()).x() + viewport.property('contentX') + header.width()
    assert right == pytest.approx(viewport.property('contentWidth') - 8)
    assert b.editor.document == before
