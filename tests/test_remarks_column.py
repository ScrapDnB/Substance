"""The last, unlabelled column remains available for notes with checks off."""
import pytest
from PySide6.QtCore import QObject
from PySide6.QtTest import QTest

from test_workflow_ui import workflow_ui  # noqa: F401
from test_workflow_sections import visual_find


@pytest.mark.parametrize('mode', ['timing', 'translation'])
@pytest.mark.parametrize('kind', ['note', 'proposal'])
def test_notes_keep_the_unlabelled_last_column_visible_with_checks_disabled(workflow_ui, tmp_path, mode, kind):
    b, w, _ = workflow_ui
    assert b._save_path(str(tmp_path / 'notes.substance'))
    b.setMode(mode)
    for key in ('readingSpeed', 'lineLength', 'lineCount', 'overlaps'):
        b.setReviewSetting(key, False)
    table = w.findChild(QObject, 'subtitleTablePanel')
    assert not table.property('showRemarks')
    b.select(1, 0)
    assert b.addReview(kind, 'Проверить эту реплику', 'Другой текст' if kind == 'proposal' else '')
    QTest.qWait(40)
    assert not b.checksEnabled and b.hasDocumentRemarks
    assert table.property('showRemarks') and table.property('statusWidth') == 96
    header = w.findChild(QObject, 'tableRemarksHeader')
    assert header.property('text') == '' and header.property('visible')
    assert header.parentItem().childItems()[-1] == header
    # Both the header and row reserve the rightmost cell, after all text fields.
    cell = visual_find(w.contentItem(), 'tableRemarks_1')
    assert cell is not None and cell.property('visible')
    assert cell.parentItem().childItems()[-1] == cell
    assert cell.x() + cell.width() == pytest.approx(cell.parentItem().width() - 8)
    assert ('✎' if kind == 'note' else '↔') in cell.property('text')
    # Visibility is based on the whole document, even if search hides the note.
    b.setSearch('Hello', False, False)
    QTest.qWait(20)
    assert b.visibleCount == 1 and table.property('showRemarks')
    b.setSearch('', False, False)
    b.reviewAction(b.reviewEntries[0]['id'], 'resolved' if kind == 'note' else 'rejected')
    assert b.hasDocumentRemarks and table.property('showRemarks')
    b.undo()  # Restore the open note/proposal.
    b.undo()  # Remove the note/proposal itself.
    assert not b.hasDocumentRemarks and not table.property('showRemarks')
    b.redo()
    assert b.hasDocumentRemarks and table.property('showRemarks')


def test_deleting_the_noted_cue_releases_column_and_undo_restores_it(workflow_ui, tmp_path):
    b, w, _ = workflow_ui
    assert b._save_path(str(tmp_path / 'notes.substance'))
    for key in ('readingSpeed', 'lineLength', 'lineCount', 'overlaps'):
        b.setReviewSetting(key, False)
    assert b.addReview('note', 'Заметка', '')
    assert b.hasDocumentRemarks
    b.deleteLines()
    assert not b.hasDocumentRemarks
    assert not w.findChild(QObject, 'subtitleTablePanel').property('showRemarks')
    b.undo()
    assert b.hasDocumentRemarks
    assert w.findChild(QObject, 'subtitleTablePanel').property('showRemarks')
