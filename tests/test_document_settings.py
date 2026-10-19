"""Document options are staged; program options only seed future documents."""
from copy import deepcopy

import pytest
from PySide6.QtCore import QObject, QMetaObject
from PySide6.QtQml import QQmlExpression, qmlContext
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from substance.backend import Backend
from substance.document import load_document
from test_workflow_ui import workflow_ui  # noqa: F401


def invoke(item, method='click'):
    assert item is not None
    assert QMetaObject.invokeMethod(item, method)
    QTest.qWait(30)


@pytest.mark.parametrize('project', [False, True])
def test_defaults_do_not_touch_current_document_selection_warnings_or_analysis(workflow_ui, tmp_path, project):
    b, w, messages = workflow_ui
    if project:
        assert b._save_path(str(tmp_path / 'work.substance'))
    b.editor.update(0, text='A' * 90)
    b.tools.analyze('checks', {'timing': False})
    document = deepcopy(b.editor.document)
    limits = b.cpsLimit, b.lineLimit
    issues = b.current['issues']
    selection = b.currentIndex, set(b.selection)
    dirty = b.dirty
    b.setDefaultReviewSetting('readingSpeed', False)
    b.setDefaultReviewSetting('lineLength', False)
    b.setDefaultReviewSetting('cpsLimit', 33)
    b.setDefaultReviewSetting('lineLimit', 60)
    b.setDefaultReviewSetting('lineCountLimit', 3)
    b.preference('importEncoding', 'cp1251')
    assert b.editor.document == document
    assert (b.cpsLimit, b.lineLimit) == limits
    assert b.current['issues'] == issues
    assert (b.currentIndex, b.selection) == selection
    assert b.dirty == dirty and not b.tools.stale
    # Defaults survive application restart and seed a new empty document.
    b.settings.sync()
    restored = Backend()
    try:
        assert restored.defaultReviewSettings == b.defaultReviewSettings
        assert restored.importEncoding == 'cp1251'
        assert restored.reviewSettings['readingSpeed'] is False
        assert (restored.cpsLimit, restored.lineLimit) == (33, 60)
    finally:
        restored.shutdown()
    # The UI exposes defaults regardless of whether the current file is a project.
    settings = w.findChild(QObject, 'settingsDialog')
    invoke(settings, 'open')
    w.findChild(QObject, 'settingsNavigation').setProperty('page', 4)
    QTest.qWait(30)
    assert not settings.findChild(QObject, 'defaultReadingSpeedCheck').property('checked')
    invoke(settings.findChild(QObject, 'defaultReadingSpeedCheck'))
    assert b.defaultReviewSettings['readingSpeed'] is True
    assert b.editor.document == document
    settings.close()
    # Preserve the edited document to avoid a confirmation dialog in this test.
    assert b._save_path(str(tmp_path / 'before-new.substance'))
    b.newDocument()
    assert b.count == 0
    assert (b.cpsLimit, b.lineLimit) == (33, 60)
    assert b.reviewSettings['lineLength'] is False
    assert b.reviewSettings['lineCountLimit'] == 3
    assert not b.dirty
    assert not [m for m in messages if 'Unable to assign' in m or 'TypeError' in m], messages


@pytest.mark.parametrize('suffix', ['.ass', '.substance'])
def test_document_checks_roundtrip_independent_of_later_defaults(workflow_ui, tmp_path, suffix):
    b, _, _ = workflow_ui
    b.setReviewSetting('readingSpeed', False)
    b.preference('cpsLimit', '28')
    b.preference('lineLimit', '57')
    expected = dict(b.reviewSettings)
    output = tmp_path / ('settings' + suffix)
    assert b._save_path(str(output))
    b.setDefaultReviewSetting('cpsLimit', 10)
    b.setDefaultReviewSetting('lineLength', False)
    b._set_document(load_document(output), str(output))
    assert b.reviewSettings == expected
    assert not b.dirty


def test_file_menu_opens_a_separate_document_window_and_program_settings_have_no_document_page(workflow_ui):
    b, w, messages = workflow_ui
    settings = w.findChild(QObject, 'settingsDialog')
    pages = settings.property('pages').toVariant()
    assert len(pages) == 7
    assert 'Документ' not in [page['title'] for page in pages]
    assert settings.findChild(QObject, 'documentFps') is None
    invoke(settings, 'openLanguageSettings')
    assert w.findChild(QObject, 'settingsNavigation').property('page') == 6
    settings.close()
    b.setSection('post')
    invoke(w.findChild(QObject, 'documentSettingsMenuItem'), 'triggered')
    dialog = w.findChild(QObject, 'documentSettingsDialog')
    assert dialog.property('visible')
    assert dialog.property('embeddedHost') is None
    assert dialog.transientParent() == w
    assert w.property('modalOpen')
    dialog.close()
    assert not [m for m in messages if any(s in m for s in ('TypeError', 'ReferenceError', 'Unable to assign'))], messages


def test_document_options_apply_atomically_cancel_and_undo(workflow_ui):
    b, w, _ = workflow_ui
    dialog = w.findChild(QObject, 'documentSettingsDialog')
    before = deepcopy(b.editor.document)
    defaults = b.defaultReviewSettings
    invoke(dialog, 'open')
    dialog.findChild(QObject, 'documentFps').setProperty('text', '25')
    dialog.findChild(QObject, 'documentEncoding').setProperty('currentIndex', 1)
    invoke(dialog.findChild(QObject, 'documentReadingSpeedCheck'))
    # Numeric fields are committed through their normal QML edit signal.
    expression = QQmlExpression(qmlContext(dialog), dialog,
        'checks = Object.assign({}, checks, {cpsLimit: 30, lineLimit: 55, lineCountLimit: 3})')
    expression.evaluate()
    assert not expression.hasError()
    assert b.editor.document == before
    invoke(dialog.findChild(QObject, 'documentSettingsCancel'))
    assert b.editor.document == before and not dialog.property('visible')
    invoke(dialog, 'open')
    assert dialog.findChild(QObject, 'documentReadingSpeedCheck').property('checked')
    dialog.findChild(QObject, 'documentFps').setProperty('text', '25')
    dialog.findChild(QObject, 'documentEncoding').setProperty('currentIndex', 1)
    invoke(dialog.findChild(QObject, 'documentReadingSpeedCheck'))
    expression.evaluate()
    revisions = len(b.editor.undo_stack)
    invoke(dialog.findChild(QObject, 'documentSettingsApply'))
    assert not dialog.property('visible')
    assert b.fps == 25 and b.encoding == 'cp1251'
    assert b.reviewSettings['readingSpeed'] is False
    assert (b.cpsLimit, b.lineLimit, b.reviewSettings['lineCountLimit']) == (30, 55, 3)
    assert b.defaultReviewSettings == defaults
    assert len(b.editor.undo_stack) == revisions + 1
    b.undo()
    assert b.editor.document == before
    b.redo()
    assert b.fps == 25 and b.cpsLimit == 30


def test_invalid_fps_is_rejected_and_replacement_closes_old_document_options(workflow_ui, monkeypatch):
    b, w, _ = workflow_ui
    dialog = w.findChild(QObject, 'documentSettingsDialog')
    invoke(dialog, 'open')
    before = deepcopy(b.editor.document)
    errors = []
    monkeypatch.setattr(b, 'show_error', errors.append)
    for fps in (0, 121, float('nan'), float('inf')):
        assert not b.documentSettings(fps, 'utf-8', b.reviewSettings)
        assert b.editor.document == before
    dialog.findChild(QObject, 'documentFps').setProperty('text', '')
    assert not dialog.findChild(QObject, 'documentSettingsApply').property('enabled')
    b.newDocument()
    assert not dialog.property('visible')
    assert errors


def test_recovery_keeps_document_defaults_snapshot(workflow_ui, monkeypatch):
    b, _, _ = workflow_ui
    b.stage('text', 'Unsaved work')
    b.flush()
    before = dict(b.reviewSettings)
    b.autosave()
    b.setDefaultReviewSetting('cpsLimit', 45)
    b.setDefaultReviewSetting('lineLength', False)
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    b.restore_recovery()
    assert b.reviewSettings == before
    assert b.defaultReviewSettings['cpsLimit'] == 45


def test_changing_only_checks_preserves_encoding_bom_and_fps_origin(workflow_ui):
    b, _, _ = workflow_ui
    b.editor.document.bom = True
    b.editor.document.metadata['fps_source'] = 'video'
    options = dict(b.reviewSettings, readingSpeed=False)
    assert b.documentSettings(b.fps, b.encoding, options)
    assert b.editor.document.bom is True
    assert b.editor.document.metadata['fps_source'] == 'video'
