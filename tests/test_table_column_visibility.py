"""Header context menus choose columns independently for each editing mode."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QObject, QPointF, Qt
from PySide6.QtTest import QTest

from substance.appearance import AppearanceSettings
from test_workflow_ui import workflow_ui  # noqa: F401
from test_workflow_sections import visual_find


def open_columns_menu(w):
    header = w.findChild(QObject, 'tableColumnsHeaderArea')
    point = header.mapToScene(QPointF(20, header.height() / 2)).toPoint()
    QTest.mouseClick(w, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, point)
    # Fluent animates popup scale/position before items accept pointer clicks.
    QTest.qWait(250)
    assert w.findChild(QObject, 'tableColumnsMenu').property('visible')


def choose(w, key):
    item = visual_find(w.contentItem(), 'columnOption_' + key)
    assert item is not None and item.property('visible')
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(25)


@pytest.mark.parametrize('mode,key,cell', [('timing', 'actor', 'tableActor_0'), ('timing', 'text', 'tableSource_0'),
                                         ('translation', 'original', 'tableSource_0'), ('translation', 'translation', 'tableTranslation_0')])
def test_header_menu_hides_columns_without_editing_document_and_restores_on_toggle(workflow_ui, mode, key, cell):
    b, w, messages = workflow_ui
    b.setMode(mode)
    b.appearance.setValue('general', 'wrapRows', True)
    QTest.qWait(50)
    before = deepcopy(b.editor.document)
    selected = b.currentIndex, set(b.selection)
    open_columns_menu(w)
    choose(w, key)
    assert b.appearance.columnVisibility[mode][key] is False
    assert not visual_find(w.contentItem(), cell).property('visible')
    assert b.editor.document == before and not b.dirty
    assert (b.currentIndex, b.selection) == selected
    # Hidden text must not produce tall rows by wrapping into zero width.
    row = visual_find(w.contentItem(), cell).parentItem().parentItem()
    assert row.height() < 100
    open_columns_menu(w)
    choose(w, key)
    assert visual_find(w.contentItem(), cell).property('visible')
    assert b.appearance.columnVisibility[mode][key] is True
    assert not [m for m in messages if any(s in m for s in ('TypeError', 'ReferenceError', 'Binding loop', 'Unable to assign'))], messages


def test_visibility_is_saved_per_mode_and_show_all_keeps_widths(workflow_ui):
    b, w, _ = workflow_ui
    b.appearance.setColumnWidth('timing', 'actor', 170)
    open_columns_menu(w)
    choose(w, 'actor')
    b.setMode('translation')
    QTest.qWait(35)
    assert visual_find(w.contentItem(), 'tableActor_0').property('visible')
    open_columns_menu(w)
    assert visual_find(w.contentItem(), 'columnOption_end') is None
    choose(w, 'original')
    b.setMode('timing')
    QTest.qWait(35)
    assert not visual_find(w.contentItem(), 'tableActor_0').property('visible')
    assert visual_find(w.contentItem(), 'tableSource_0').property('visible')
    b.settings.sync()
    restored = AppearanceSettings(b.settings)
    assert restored.columnVisibility == b.appearance.columnVisibility
    b.appearance.showAllColumns('timing')
    assert visual_find(w.contentItem(), 'tableActor_0').property('visible')
    assert b.appearance.columnWidths['timing']['actor'] == 170
    assert b.appearance.columnVisibility['translation']['original'] is False


def test_notes_column_can_be_explicitly_hidden_and_shown_and_menu_survives_all_columns_hidden(workflow_ui):
    b, w, _ = workflow_ui
    for key in ('readingSpeed', 'lineLength', 'lineCount', 'overlaps'):
        b.setReviewSetting(key, False)
    table = w.findChild(QObject, 'subtitleTablePanel')
    assert not table.property('showRemarks')
    b.appearance.setColumnVisible('timing', 'remarks', True)
    assert table.property('showRemarks')
    open_columns_menu(w)
    choose(w, 'remarks')
    assert not table.property('showRemarks')
    for key in ('number', 'start', 'end', 'portrait', 'actor', 'text'):
        b.appearance.setColumnVisible('timing', key, False)
    QTest.qWait(30)
    assert table.property('fixedWidth') == table.property('textWidth') == 0
    open_columns_menu(w)
    item = visual_find(w.contentItem(), 'showAllTableColumns')
    point = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)
    assert table.property('showRemarks')
    assert table.property('sourceWidth') > 0
    assert visual_find(w.contentItem(), 'tableNumber_0').property('visible')
