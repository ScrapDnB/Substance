from copy import deepcopy
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, QUrl, Qt, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import Cue, Document
from substance.macos import MacOSIntegration
from substance import visuals  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]


def test_semantic_dialog_is_available_and_ordinary_alignment_has_text_source(ui):
    b, w = ui
    assert w.findChild(QObject, 'semanticTimingMenuItem')
    b.openAlignment()
    ordinary = w.findChild(QObject, 'alignmentDialog')
    assert ordinary.findChild(QObject, 'alignmentTextSource')
    ordinary.close()
    b.openSemanticTiming()
    dialog = w.findChild(QObject, 'semanticTimingDialog')
    assert dialog.property('visible')
    assert dialog.findChild(QObject, 'semanticRole').property('count') == 3
    mode = dialog.findChild(QObject, 'semanticMode')
    assert mode.property('count') == 2 and mode.property('currentIndex') == 0
    assert not dialog.findChild(QObject, 'semanticLineWidth').property('enabled')
    assert not dialog.findChild(QObject, 'semanticMaxDuration').property('enabled')
    mode.setProperty('currentIndex', 1)
    assert dialog.findChild(QObject, 'semanticLineWidth').property('enabled')
    assert dialog.findChild(QObject, 'semanticMaxDuration').property('enabled')
    assert dialog.findChild(QObject, 'semanticAudioLanguage')
    assert dialog.findChild(QObject, 'semanticTextLanguage')
    assert not dialog.findChild(QObject, 'semanticAnalyze').property('enabled')
    assert not dialog.findChild(QObject, 'semanticApply').property('enabled')
    dialog.close()


@pytest.mark.parametrize('size', [(820, 700), (1280, 940)])
def test_semantic_setup_and_review_fit_window_and_show_both_columns(ui, size, monkeypatch):
    from substance.editor_tools import Proposal
    b, w = ui
    b.openSemanticTiming()
    dialog = w.findChild(QObject, 'semanticTimingDialog')
    dialog.resize(*size)
    QTest.qWait(50)
    for name in ('semanticMode', 'semanticRole', 'semanticAudioLanguage', 'semanticAnalyze', 'semanticApply'):
        item = dialog.findChild(QObject, name)
        point = item.mapToScene(QPointF())
        assert point.x() >= 0 and point.y() >= 0, name
        assert point.x()+item.width() <= dialog.width()+1, name
        assert point.y()+item.height() <= dialog.height()+1, name
    b.tools._snapshot = deepcopy(b.editor.document)
    b.tools._editor = b.editor
    b.tools._media_context = b.tools._context()
    cue = deepcopy(b.editor.document.cues[0])
    cue.original = cue.text = 'A real English phrase.'
    cue.translation = 'Настоящая русская фраза.'
    b.tools._proposals = [Proposal([cue.id], [cue], 'Проверка разбиения', False, True, True)]
    b.tools._analysis_ready = True
    b.tools.changed.emit()
    b.tools.analysisCompleted.emit()
    QTest.qWait(50)
    assert dialog.property('reviewing')
    assert b.tools.preview['afterCues'][0]['original'] == cue.original
    assert b.tools.preview['afterCues'][0]['translation'] == cue.translation
    play = dialog.findChild(QObject, 'toolPlayAfter')
    point = play.mapToScene(QPointF())
    assert 0 <= point.y() and point.y()+play.height() <= dialog.height()
    assert dialog.findChild(QObject, 'semanticReview').height() < dialog.height()
    played = []
    monkeypatch.setattr(b.media_controller, 'playRange', lambda start, end: played.append((start, end)))
    b.tools.playFragment(0, 0)
    assert played == [(cue.start, cue.end)]
    b.tools.checkAll(True)
    assert b.tools.canApply
    assert dialog.findChild(QObject, 'semanticApply').property('enabled')
    b.tools.invalidate()
    assert not b.tools.canApply
    dialog.close()


def test_uncertain_semantic_result_can_be_selected_applied_and_undone_in_dialog(ui):
    import numpy as np
    from substance.semantic_timing import semantic_plan

    class Encoder:
        def encode(self, texts):
            return np.array([[1., 0.] if 'world' in text.lower() else [0., 1.] for text in texts])

    b, w = ui
    original = deepcopy(b.editor.document)
    b.openSemanticTiming()
    dialog = w.findChild(QObject, 'semanticTimingDialog')
    proposals = semantic_plan(original, [0], [{'text': 'Music.', 'start': 500, 'end': 1500}],
                              Encoder(), {'role': 'original'}, detector=lambda _: ('en', 1))
    b.tools._snapshot = deepcopy(original)
    b.tools._editor = b.editor
    b.tools._media_context = b.tools._context()
    b.tools._proposals = proposals
    b.tools._analysis_ready = True
    b.tools.changed.emit()
    b.tools.analysisCompleted.emit()
    QTest.qWait(50)
    assert b.tools.rows[0]['uncertain']
    assert b.tools.preview['afterCues'][0]['warning'].startswith('Неоднозначное')
    assert not dialog.findChild(QObject, 'semanticApply').property('enabled')
    current = dialog.findChild(QObject, 'alignmentAcceptCurrent')
    assert current.property('enabled')
    click(dialog, current)
    assert dialog.findChild(QObject, 'semanticApply').property('enabled')
    click(dialog, dialog.findChild(QObject, 'semanticApply'))
    assert b.editor.document.cues[0].start == 500
    assert b.editor.document.cues[0].extras['semantic_timing']['uncertain']
    assert b.editor.document.source_lines == original.source_lines
    b.undo()
    assert b.editor.document == original
    dialog.close()


@pytest.fixture
def ui(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    if QQuickStyle.name() != 'Fusion':
        QQuickStyle.setStyle('Fusion')
    b = Backend()
    doc = Document()
    for start, end, text in [(0, 2000, r'{\i1}Hello  world !'), (500, 1500, 'Second'), (2200, 4000, 'Next')]:
        c = Cue(start=start, end=end, text=text, original=text, character='Alice')
        doc.register_source(c)
        doc.cues.append(c)
    b._set_document(doc, '')
    b.select(0)
    messages = []
    handler = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', b)
    engine.load(QUrl.fromLocalFile(str(ROOT / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    w = engine.rootObjects()[0]
    QTest.qWait(80)
    yield b, w
    b.shutdown()
    w.hide()
    shiboken6.delete(w)
    shiboken6.delete(engine)
    qInstallMessageHandler(handler)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign', 'is not a function', 'Non-existent'))], messages


def click(window, obj):
    point = obj.mapToScene(QPointF(obj.width() / 2, obj.height() / 2)).toPoint()
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


def test_toolbar_opens_all_tools_and_repairs_with_one_undo(ui):
    b, w = ui
    original = deepcopy(b.editor.document)
    dialog = w.findChild(QObject, 'editorToolsDialog')
    for button, kind in [('toolbarChecks', 'checks'), ('toolbarReflow', 'balance'), ('toolbarAlignment', 'align'), ('toolbarScenes', 'scenes')]:
        click(w, w.findChild(QObject, button))
        target = w.findChild(QObject, 'alignmentDialog') if kind == 'align' else dialog
        assert target.property('visible')
        if kind != 'align':
            assert target.property('kind') == kind
        target.close()
    b.openChecks()
    QTest.qWait(30)
    button = dialog.findChild(QObject, 'analyzeToolsButton')
    click(dialog, button)
    assert b.tools.rows and b.tools.canApply
    assert dialog.findChild(QObject, 'toolProposalList').property('count') > 0
    click(dialog, dialog.findChild(QObject, 'applyToolsButton'))
    assert b.editor.document.cues[0].text == r'{\i1}Hello world!'
    b.undo()
    assert b.editor.document == original
    dialog.close()


def test_tracks_background_switch_retains_view_and_edits_selected_blocks(ui):
    b, w = ui
    pane = w.findChild(QObject, 'timingAudio')
    wave = pane.findChild(QObject, 'audioWaveform')
    wave.scrollTime(500)
    previous = wave.property('viewStart'), wave.property('span')
    selector = pane.findChild(QObject, 'audioDisplaySelector')
    point = selector.mapToScene(QPointF(selector.width() * 3 / 4, selector.height() / 2)).toPoint()
    QTest.mouseClick(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    assert b.tools.displayMode == 'spectrum'
    assert selector.property('count') == 2
    QTest.qWait(80)
    assert w.findChild(QObject, 'subtitleTracks').property('visible')
    assert (wave.property('viewStart'), wave.property('span')) == previous
    assert len(b.tools.lanes) == 2
    before = deepcopy(b.editor.document)
    b.tools.moveCues([0, 1], 300)
    assert [c.start for c in b.editor.document.cues[:2]] == [300, 800]
    b.undo()
    assert b.editor.document == before
    b.tools.setDisplayMode('spectrum')
    QTest.qWait(30)
    assert wave.property('spectral')
    b.tools.setDisplayMode('wave')
    assert not wave.property('spectral')


def test_dialog_rejects_stale_preview_and_reports_missing_media(ui):
    b, w = ui
    b.tools.analyze('checks', {'timing': False})
    b.editor.update(0, text='Manual')
    assert not b.tools.apply()
    assert 'изменился' in b.tools.status
    assert b.editor.document.cues[0].text == 'Manual'
    b.tools.analyze('align', {})
    assert 'Откройте' in b.tools.status
    b.tools.analyze('scenes', {})
    assert 'Откройте' in b.tools.status


def test_native_toolbar_has_visible_tools(ui, monkeypatch):
    b, w = ui
    monkeypatch.setattr(MacOSIntegration, 'refresh_palette', lambda *args: None)
    native = MacOSIntegration(b)
    defaults = native.default_identifiers
    for key in ['checks', 'reflow', 'align', 'point-sync', 'time-shift', 'scenes']:
        assert 'substance.' + key in defaults
    assert 'substance.tracks' not in defaults
    assert 'substance.tracks' not in native.ACTIONS
    assert w.findChild(QObject, 'toolbarTracks') is None
    native.perform('substance.checks')
    assert w.findChild(QObject, 'editorToolsDialog').property('visible')
    w.findChild(QObject, 'editorToolsDialog').close()


@pytest.mark.parametrize('display', ['wave', 'spectrum'])
def test_real_track_drag_changes_interval_and_is_undoable(ui, display):
    b, w = ui
    b.tools.setDisplayMode(display)
    QTest.qWait(80)
    block = visual_find(w.contentItem(), 'trackCue_2')
    assert block is not None
    start = b.editor.document.cues[2].start
    point = block.mapToScene(QPointF(block.width() / 2, block.height() / 2)).toPoint()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(w, point + QPointF(45, 0).toPoint(), 30)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point + QPointF(45, 0).toPoint())
    QTest.qWait(60)
    assert b.editor.document.cues[2].start > start
    assert b.editor.document.cues[2].end - b.editor.document.cues[2].start == 1800
    b.undo()
    assert b.editor.document.cues[2].start == start


def test_tracks_use_full_height_for_solo_cues_and_separate_dense_overlaps(ui):
    b, w = ui
    doc = Document(cues=[Cue(start=0, end=500, text='Solo before'),
                         *[Cue(start=1000, end=2000, text=f'Take {i}') for i in range(6)],
                         Cue(start=2000, end=2500, text='Solo after')])
    b._set_document(doc, '')
    QTest.qWait(60)
    tracks = w.findChild(QObject, 'subtitleTracks')
    for index in (0, 7):
        block = visual_find(w.contentItem(), f'trackCue_{index}')
        assert block.y() == pytest.approx(3)
        assert block.height() == pytest.approx(tracks.height() - 6)
    blocks = [visual_find(w.contentItem(), f'trackCue_{i}') for i in range(1, 7)]
    for block, following in zip(blocks, blocks[1:]):
        assert block.height() > 0
        assert block.y() + block.height() < following.y()
    # Every dense take remains directly selectable, including those beyond three.
    for index, block in enumerate(blocks, 1):
        click(w, block)
        assert b.currentIndex == index


@pytest.mark.parametrize('display', ['wave', 'spectrum'])
def test_tracks_selection_keeps_view_but_explicit_center_works(ui, display):
    b, w = ui
    wave = w.findChild(QObject, 'timingAudio').findChild(QObject, 'audioWaveform')
    b.tools.setDisplayMode(display)
    wave.setViewport(700, 4000)
    previous = wave.property('viewStart'), wave.property('span')
    b.select(2)
    assert (wave.property('viewStart'), wave.property('span')) == previous
    b.select(0, Qt.KeyboardModifier.ControlModifier.value)
    b.select(1, Qt.KeyboardModifier.ShiftModifier.value)
    assert (wave.property('viewStart'), wave.property('span')) == previous
    click(w, w.findChild(QObject, 'audioCenterCue'))
    assert wave.property('viewStart') == 0
    wave.setViewport(*previous)
    b.select(2)
    assert (wave.property('viewStart'), wave.property('span')) == previous
    click(w, w.findChild(QObject, 'audioCenterCue'))
    assert wave.property('viewStart') == 1100
    assert wave.property('span') == previous[1]


def test_track_layout_reflows_after_move_and_undo(ui):
    b, w = ui
    b.tools.moveCues([1], 4000)
    QTest.qWait(40)
    tracks = w.findChild(QObject, 'subtitleTracks')
    block = visual_find(w.contentItem(), 'trackCue_0')
    assert block.height() == pytest.approx(tracks.height() - 6)
    b.undo()
    QTest.qWait(40)
    block = visual_find(w.contentItem(), 'trackCue_0')
    assert block.height() == pytest.approx(tracks.height() / 2 - 6)


@pytest.mark.parametrize('edge', ['start', 'end'])
def test_track_resize_from_full_height_block_is_undoable(ui, edge):
    b, w = ui
    QTest.qWait(40)
    block = visual_find(w.contentItem(), 'trackCue_2')
    before = deepcopy(b.editor.document.cues[2])
    x = 2 if edge == 'start' else block.width() - 2
    point = block.mapToScene(QPointF(x, block.height() / 2)).toPoint()
    end_point = point + QPointF(35, 0).toPoint()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(w, end_point, 30)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, end_point)
    QTest.qWait(40)
    after = b.editor.document.cues[2]
    if edge == 'start':
        assert after.start > before.start and after.end == before.end
    else:
        assert after.start == before.start and after.end > before.end
    b.undo()
    assert b.editor.document.cues[2] == before


@pytest.mark.parametrize('side,direction', [('left', 1), ('right', -1)])
def test_drag_joint_previews_both_cues_and_commits_one_undo(ui, side, direction):
    b, w = ui
    b._set_document(Document(cues=[Cue(start=0, end=2000, text='Left'),
                                  Cue(start=2000, end=4000, text='Right')]), '')
    wave = w.findChild(QObject, 'timingAudio').findChild(QObject, 'audioWaveform')
    wave.setViewport(100, 5000)
    QTest.qWait(40)
    marker = 2000 + direction * round(40 * 5000 / wave.width()) + 3
    b.media_controller.keyframes = [marker]
    left = visual_find(w.contentItem(), 'trackCue_0')
    right = visual_find(w.contentItem(), 'trackCue_1')
    block = left if side == 'left' else right
    x = block.width() - 2 if side == 'left' else 2
    point = block.mapToScene(QPointF(x, block.height() / 2)).toPoint()
    target = point + QPointF(direction * 40, 0).toPoint()
    before = deepcopy(b.editor.document)
    widths = left.width(), right.width()
    history = len(b.editor.undo_stack)
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, point)
    QTest.mouseMove(w, target, 30)
    QTest.qWait(20)
    assert b.editor.document == before  # Preview only until release.
    assert direction * (left.width() - widths[0]) > 0
    assert direction * (right.width() - widths[1]) < 0
    assert left.x() + left.width() == pytest.approx(right.x())
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, target)
    QTest.qWait(40)
    a, c = b.editor.document.cues
    assert a.end == c.start and direction * (a.end - 2000) > 0
    assert a.end == marker
    assert a.start == 0 and c.end == 4000
    assert len(b.editor.undo_stack) == history + 1
    assert wave.property('viewStart') == 100 and wave.property('span') == 5000
    b.undo()
    assert b.editor.document == before
    b.redo()
    assert b.editor.document.cues[0].end == b.editor.document.cues[1].start == a.end


def test_plain_drag_shared_edge_edits_only_one_cue(ui):
    b, w = ui
    b._set_document(Document(cues=[Cue(start=0, end=2000, text='Left'),
                                  Cue(start=2000, end=4000, text='Right')]), '')
    QTest.qWait(40)
    block = visual_find(w.contentItem(), 'trackCue_1')
    point = block.mapToScene(QPointF(2, block.height() / 2)).toPoint()
    target = point + QPointF(40, 0).toPoint()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.mouseMove(w, target, 30)
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, target)
    QTest.qWait(30)
    assert b.editor.document.cues[0].end == 2000
    assert b.editor.document.cues[1].start > 2000


def test_joint_clamps_both_durations_snaps_and_rejects_stale_drag(ui):
    b, w = ui
    b._set_document(Document(cues=[Cue(start=0, end=2000, text='Left'),
                                  Cue(start=2000, end=4000, text='Right')]), '')
    b.tools.beginTrackEdit()
    assert b.tools.moveJoint(0, 1, -500)
    assert b.editor.document.cues[0].end == b.editor.document.cues[1].start == 10
    b.undo()
    assert b.tools.moveJoint(0, 1, 5000)
    assert b.editor.document.cues[0].end == b.editor.document.cues[1].start == 3990
    b.undo()
    assert b.tools.snapJointTime(0, 1, 2010, 50) == 2010  # Do not snap to the old joint.
    b.media_controller.keyframes = [2030]
    assert b.tools.snapJointTime(0, 1, 2010, 50) == 2030
    b.tools.beginTrackEdit()
    b.editor.update(1, start=2100)
    before = deepcopy(b.editor.document)
    assert not b.tools.moveJoint(0, 1, 2500)
    assert b.editor.document == before
    assert b.tools._drag_context is None


def test_cancel_joint_drag_restores_preview_without_changing_document(ui):
    b, w = ui
    b._set_document(Document(cues=[Cue(start=0, end=2000, text='Left'),
                                  Cue(start=2000, end=4000, text='Right')]), '')
    QTest.qWait(40)
    before = deepcopy(b.editor.document)
    right = visual_find(w.contentItem(), 'trackCue_1')
    point = right.mapToScene(QPointF(2, right.height() / 2)).toPoint()
    QTest.mousePress(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, point)
    QTest.mouseMove(w, point + QPointF(40, 0).toPoint(), 30)
    assert right.property('displayStart') > 2000
    visual_find(w.contentItem(), 'trackDrag_1').ungrabMouse()
    QTest.qWait(20)
    assert right.property('displayStart') == 2000
    assert b.editor.document == before and not b.editor.undo_stack
    QTest.mouseRelease(w, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.AltModifier, point)


def test_joint_updates_authored_sources_and_undo_restores_them(ui):
    b, w = ui
    doc = Document(cues=[Cue(start=0, end=2000, text='Left', original='Left', extras={'authoring': True}),
                         Cue(start=2000, end=4000, text='Right', original='Right', extras={'authoring': True})])
    for cue in doc.cues:
        doc.register_source(cue)
    b._set_document(doc, '')
    before = deepcopy(b.editor.document)
    assert b.tools.moveJoint(0, 1, 2500)
    a, c = b.editor.document.cues
    assert b.editor.document.source_lines[a.source_ids[0]]['end'] == 2.5
    assert b.editor.document.source_lines[c.source_ids[0]]['start'] == 2.5
    assert a.text == 'Left' and c.text == 'Right'
    b.undo()
    assert b.editor.document == before


def test_toolbar_fits_at_minimum_window_and_maximum_scale(ui):
    b, w = ui
    b.appearance.setValue('general', 'uiScale', 125)
    w.resize(980, 650)
    QTest.qWait(80)
    for name in ('toolbarMedia', 'toolbarTranscribe', 'toolbarChecks', 'toolbarReflow', 'toolbarAlignment', 'toolbarPointSync', 'toolbarShift', 'toolbarScenes', 'toolbarSettings'):
        item = w.findChild(QObject, name)
        point = item.mapToScene(QPointF(0, 0))
        assert point.x() >= 0
        assert point.x() + item.width() <= w.width(), name


def test_merging_current_second_cue_keeps_selection_on_result(ui):
    b, w = ui
    b.editor.update(0, start=0, end=400)
    b.editor.update(1, start=450, end=1400)
    b.select(1)
    b.tools.analyze('merge', {'gap': 100, 'minimum': 1000})
    assert b.tools.canApply
    assert b.tools.apply()
    assert b.currentIndex == 0 and b.selection == {0}
    assert len(b.editor.document.cues[0].source_ids) == 2


@pytest.mark.parametrize('display', ['wave', 'spectrum'])
def test_track_blocks_overlay_background_and_remain_translucent(ui, display):
    b, w = ui
    b.tools.setDisplayMode(display)
    pane = w.findChild(QObject, 'timingAudio')
    before_height = pane.height()
    QTest.qWait(50)
    wave = pane.findChild(QObject, 'audioWaveform')
    tracks = pane.findChild(QObject, 'subtitleTracks')
    assert tracks.parentItem() == wave.parentItem()
    assert tracks.x() == wave.x() and tracks.width() == wave.width()
    assert tracks.y() == wave.property('bodyTop')
    assert wave.isVisible() and not wave.property('showCueRange')
    assert pane.height() == before_height
    for i in range(3):
        block = visual_find(w.contentItem(), f'trackCue_{i}')
        assert block and 0 < block.property('color').alphaF() < 0.4
    b.tools.setDisplayMode('spectrum' if display == 'wave' else 'wave')
    assert tracks.isVisible() and not wave.property('showCueRange')


def test_alignment_setup_explains_scope_and_hides_technical_options(ui):
    b, w = ui
    b.openAlignment()
    QTest.qWait(40)
    dialog = w.findChild(QObject, 'alignmentDialog')
    assert dialog.property('visible')
    assert dialog.property('stage') == 0
    assert dialog.findChild(QObject, 'alignmentScope').property('currentIndex') == 0
    assert not dialog.findChild(QObject, 'alignmentModel').property('visible')
    assert not dialog.findChild(QObject, 'alignmentAnalyze').property('enabled')
    toggle = dialog.findChild(QObject, 'alignmentAdvancedToggle')
    click(dialog, toggle)
    assert dialog.findChild(QObject, 'alignmentModel').property('visible')
    assert dialog.findChild(QObject, 'alignmentCpu').property('visible')
    dialog.close()


def test_alignment_result_review_selects_changes_and_applies_one_undo(ui):
    from substance.editor_tools import Proposal
    b, w = ui
    before = deepcopy(b.editor.document)
    b.openAlignment()
    tools = b.tools
    tools._editor = b.editor
    tools._snapshot = deepcopy(before)
    tools._kind = 'align'
    tools._media_context = tools._context()
    tools._analysis_count = 3
    first, second = deepcopy(before.cues[0]), deepcopy(before.cues[1])
    first.start += 100
    second.end += 200
    tools._result = [Proposal([first.id], [first], 'Совпадение текста 100%'),
                     Proposal([second.id], [second], 'Прослушайте', False, review=True)]
    tools._finished({'error': '', 'cancelled': False})
    QTest.qWait(60)
    dialog = w.findChild(QObject, 'alignmentDialog')
    assert dialog.property('stage') == 1
    assert tools.summary == {'analyzed': 3, 'changes': 2, 'review': 1, 'unmatched': 0, 'selected': 1}
    tools.previewRow(1)
    QTest.qWait(30)
    assert dialog.findChild(QObject, 'alignmentResultList').property('currentIndex') == 1
    accept = dialog.findChild(QObject, 'alignmentAcceptCurrent')
    assert not accept.property('checked')
    click(dialog, accept)
    assert tools.summary['selected'] == 2
    assert tools.preview['endText'] == '00:00:01.500'
    assert tools.preview['afterEndText'] == '00:00:01.700'
    click(dialog, dialog.findChild(QObject, 'alignmentBack'))
    assert dialog.property('stage') == 0
    # Selection/refresh signals must not force a jump back to the result page.
    b.select(2)
    QTest.qWait(20)
    assert dialog.property('stage') == 0
    dialog.setProperty('stage', 1)
    click(dialog, dialog.findChild(QObject, 'alignmentApply'))
    assert not dialog.property('visible')
    assert b.editor.document.cues[0].start == 100
    assert b.editor.document.cues[1].end == 1700
    b.undo()
    assert b.editor.document == before


def test_alignment_form_sends_current_selection_language_and_boundary_options(ui, monkeypatch):
    import sys
    from PySide6.QtCore import QMetaObject
    from substance.transcription import MODEL_BY_ID
    b, w = ui
    model = MODEL_BY_ID['small']
    b.speech.directory.mkdir(parents=True, exist_ok=True)
    # The worker is captured before execution; real model verification stays in it.
    (b.speech.directory / model.filename).write_bytes(b'test-placeholder')
    b.media_controller.path = '/test/audio.wav'
    jobs = []
    monkeypatch.setattr('substance.tools_controller.whisper_executable', lambda: sys.executable)
    monkeypatch.setattr(b.tools, '_start', jobs.append)
    b.openAlignment()
    dialog = w.findChild(QObject, 'alignmentDialog')
    dialog.findChild(QObject, 'alignmentLanguage').setProperty('currentIndex', 3)  # Japanese
    dialog.findChild(QObject, 'alignmentEdges').setProperty('currentIndex', 1)
    dialog.findChild(QObject, 'alignmentSearchWindow').setProperty('value', 2000)
    QMetaObject.invokeMethod(dialog, 'runAnalysis')
    assert jobs[-1].indices == [0]
    assert jobs[-1].language == 'ja'
    assert jobs[-1].options['edges'] == 'start'
    assert jobs[-1].options['maxShift'] == 2000
    b.select(2, Qt.KeyboardModifier.ControlModifier.value)
    dialog.findChild(QObject, 'alignmentScope').setProperty('currentIndex', 1)
    QMetaObject.invokeMethod(dialog, 'runAnalysis')
    assert jobs[-1].indices == [0, 2]
    dialog.close()


def test_review_preview_shows_each_split_cue_and_blocks_changed_options(ui):
    b, w = ui
    b.editor.update(0, start=0, end=6000, text='This is a long sentence with enough words to become several separate subtitle cues at the chosen line limit.')
    b.openReflow()
    b.tools.analyze('split', {'width': 20, 'minimum': 500, 'maximum': 2000})
    assert b.tools.analysisReady
    assert b.tools.preview['valid']
    preview = b.tools.preview
    assert len(preview['beforeCues']) == 1 and len(preview['afterCues']) > 1
    assert preview['afterCues'][0]['startText'] == '00:00:00.000'
    assert all(c['duration'] > 0 and c['cps'] > 0 for c in preview['afterCues'])
    b.tools.checkAll(True)  # Approximate split timing requires explicit review.
    assert b.tools.canApply
    b.tools.invalidate()
    assert b.tools.stale and not b.tools.canApply
    before = deepcopy(b.editor.document)
    assert not b.tools.apply() and b.editor.document == before
    assert 'Настройки' in b.tools.status
    w.findChild(QObject, 'editorToolsDialog').close()


@pytest.mark.parametrize('kind', ['checks', 'balance', 'align'])
def test_review_and_apply_fit_small_window_with_extra_settings(ui, kind, monkeypatch):
    # Source checkouts on CI have not compiled Whisper yet.
    monkeypatch.setattr('substance.speech.whisper_executable', lambda: '')
    b, w = ui
    b.tools.open(kind)
    dialog = w.findChild(QObject, 'alignmentDialog' if kind == 'align' else 'editorToolsDialog')
    dialog.resize(800, 680)
    toggle = dialog.findChild(QObject, 'alignmentAdvancedToggle' if kind == 'align' else 'toolsAdvancedToggle')
    toggle.setProperty('checked', True)
    QTest.qWait(60)
    review = dialog.findChild(QObject, 'alignmentResults' if kind == 'align' else 'toolsReviewPane')
    apply = dialog.findChild(QObject, 'alignmentApply' if kind == 'align' else 'applyToolsButton')
    for item in (review, apply):
        point = item.mapToScene(QPointF())
        assert point.x() >= 0 and point.y() >= 0
        assert point.x() + item.width() <= dialog.width(), kind
        assert point.y() + item.height() <= dialog.height(), kind
    assert review.height() >= 210
    dialog.close()


@pytest.mark.parametrize('size', [(800, 680), (1280, 900)])
def test_long_results_keep_card_edges_clear_of_scrollbar(ui, size):
    from PySide6.QtCore import QMetaObject
    b, w = ui
    document = Document()
    for index in range(194):
        text = 'От места поцелуя зависит, оправится ли старшая сестра от такого шока!'
        cue = Cue(start=index * 3000, end=index * 3000 + 2500, text=text, original=text)
        document.register_source(cue)
        document.cues.append(cue)
    b._set_document(document, '')
    b.openChecks()
    b.tools.analyze('checks', {'timing': False})
    dialog = w.findChild(QObject, 'editorToolsDialog')
    dialog.resize(*size)
    QTest.qWait(60)
    results = dialog.findChild(QObject, 'toolProposalList')
    scrollbar = results.findChild(QObject, 'toolResultsScrollBar')
    assert results.property('count') == 194
    assert scrollbar.property('size') < 1
    card = results.property('currentItem')
    right = card.mapToItem(results, QPointF(card.width(), 0)).x()
    assert right <= scrollbar.x() - 6
    assert results.property('contentX') == 0
    QMetaObject.invokeMethod(results, 'positionViewAtEnd')
    QTest.qWait(40)
    b.tools.previewRow(193)
    QTest.qWait(40)
    last = results.property('currentItem')
    point = last.mapToItem(results, QPointF(last.width(), last.height()))
    assert point.x() <= scrollbar.x() - 6
    assert 0 < point.y() <= results.height() + 1
    dialog.close()
