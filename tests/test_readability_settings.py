"""Optional checks apply to live warnings, analysis, saved settings, and table layout."""
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QMetaObject, QUrl, Qt
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import Cue, Document, load_document
from substance.sidebar import sidebar_filters
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def bridge(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path / 'state'))
    backend = Backend()
    cue = Cue(start=0, end=1000, text='A' * 90, original='A' * 90)
    document = Document()
    document.register_source(cue)
    document.cues.append(cue)
    backend._set_document(document, '')
    yield backend
    backend.shutdown()


def test_plain_subtitle_checks_are_document_specific_and_persist_in_ass(bridge, tmp_path):
    b = bridge
    before = b.editor.document.to_dict()
    assert len(b.current['issues']) == 2
    b.setReviewSetting('readingSpeed', False)
    assert b.current['issues'] == ['Строка длиннее 42 знаков']
    b.tools.analyze('checks', {'timing': False})
    assert any('Строка длиннее' in p.reason for p in b.tools._proposals)
    assert not any('Скорость чтения' in p.reason for p in b.tools._proposals)
    b.setReviewSetting('lineLength', False)
    assert b.tools.stale
    assert not b.current['issues']
    b.setFilter('warnings')
    assert b.visibleCount == 0
    b.tools.analyze('checks', {'timing': False})
    assert not b.tools._proposals
    assert b.editor.document.to_dict() != before
    assert b.dirty
    path = str(tmp_path / 'checks.ass')
    assert b._save_path(path)
    saved = load_document(path)
    assert saved.review_settings['readingSpeed'] is False
    assert saved.review_settings['lineLength'] is False
    assert (b.cpsLimit, b.lineLimit) == (20, 42)
    b.settings.sync()
    restored = Backend()
    try:
        assert restored.reviewSettings['readingSpeed'] is True
        assert restored.reviewSettings['lineLength'] is True
        assert (restored.cpsLimit, restored.lineLimit) == (20, 42)
    finally:
        restored.shutdown()


def test_project_check_overrides_save_and_undo_without_changing_defaults(bridge, tmp_path):
    b = bridge
    path = str(tmp_path / 'project.substance')
    assert b._save_path(path)
    b.setReviewSetting('readingSpeed', False)
    b.setReviewSetting('lineLength', False)
    assert not b.current['issues']
    assert b.save()
    saved = load_document(path)
    assert saved.review_settings['readingSpeed'] is False
    assert saved.review_settings['lineLength'] is False
    b.undo()
    assert b.reviewSettings['lineLength'] is True
    assert b.reviewSettings['readingSpeed'] is False
    assert b.current['issues'] == ['Строка длиннее 42 знаков']
    b._set_document(saved, path)
    assert not b.current['issues']
    b._set_document(Document(), '')
    assert b.reviewSettings['lineLength'] is True
    assert b.reviewSettings['readingSpeed'] is True


@pytest.mark.parametrize('project', [False, True])
def test_overlap_check_controls_live_warnings_analysis_and_persistence(bridge, tmp_path, project):
    b = bridge
    document = Document()
    for start, end in [(0, 2000), (1000, 3000)]:
        cue = Cue(start=start, end=end, text='Hello', original='Hello')
        document.register_source(cue)
        document.cues.append(cue)
    b._set_document(document, '')
    path = str(tmp_path / 'overlaps.substance')
    if project:
        assert b._save_path(path)
    before = b.editor.document.to_dict()
    assert b.current['issues'] == ['Пересечение с соседней репликой']
    b.tools.analyze('checks', {'timing': False})
    assert any('Пересечение' in p.reason for p in b.tools._proposals)
    b.setReviewSetting('overlaps', False)
    assert b.tools.stale
    assert not b.current['issues']
    b.setFilter('warnings')
    assert b.visibleCount == 0
    b.tools.analyze('checks', {'timing': False})
    assert not b.tools._proposals
    if project:
        assert b.save()
        saved = load_document(path)
        assert saved.review_settings['overlaps'] is False
        b.undo()
        assert b.reviewSettings['overlaps'] is True
        assert b.visibleCount == 1
        b._set_document(saved, path)
        assert not b.current['issues']
        b._set_document(Document(), '')
        assert b.reviewSettings['overlaps'] is True
    else:
        assert b.dirty
        assert b.editor.document.to_dict() != before
        assert b._save_path(str(tmp_path / 'overlaps.ass'))
        assert load_document(tmp_path / 'overlaps.ass').review_settings['overlaps'] is False
        b.settings.sync()
        restored = Backend()
        try:
            assert restored.reviewSettings['overlaps'] is True
        finally:
            restored.shutdown()


@pytest.mark.parametrize('project', [False, True])
@pytest.mark.parametrize('mode', ['timing', 'translation'])
def test_document_checkboxes_stage_changes_and_update_table_after_apply(bridge, tmp_path, project, mode):
    b = bridge
    if project:
        assert b._save_path(str(tmp_path / 'project.substance'))
    b.setMode(mode)
    QQuickStyle.setStyle('Fusion')
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects()
    w = engine.rootObjects()[0]
    dialog = w.findChild(QObject, 'documentSettingsDialog')
    try:
        QMetaObject.invokeMethod(dialog, 'open')
        QTest.qWait(60)
        tables = w.findChildren(QObject, 'subtitleTablePanel')
        assert len(tables) == 1 and tables[0].property('showRemarks')
        before = b.editor.document.to_dict()
        for suffix in ('ReadingSpeedCheck', 'LineLengthCheck', 'LineCountCheck', 'OverlapsCheck'):
            checkbox = dialog.findChild(QObject, 'document' + suffix)
            checkbox.forceActiveFocus()
            QTest.keyClick(dialog, Qt.Key.Key_Space)
            assert not checkbox.property('checked')
        assert b.editor.document.to_dict() == before
        assert b.checksEnabled
        assert not dialog.findChild(QObject, 'documentReadingSpeedLimit').property('enabled')
        assert dialog.findChild(QObject, 'documentReadingSpeedLimit').property('value') == 20
        assert dialog.findChild(QObject, 'documentLineLengthLimit').property('value') == 42
        QMetaObject.invokeMethod(dialog.findChild(QObject, 'documentSettingsApply'), 'click')
        QTest.qWait(30)
        assert not dialog.property('visible')
        assert not b.checksEnabled and not b.current['issues']
        assert w.findChild(QObject, 'sidebarFilters').property('count') == 4
        assert 'warnings' not in [row[0] for row in sidebar_filters(b)]
        assert not tables[0].property('showRemarks')
        assert tables[0].property('statusWidth') == 0
        b.undo()
        assert b.checksEnabled
        assert tables[0].property('showRemarks')
        assert w.findChild(QObject, 'sidebarFilters').property('count') == 5
    finally:
        dialog.close()
        shiboken6.delete(w)
        shiboken6.delete(engine)
