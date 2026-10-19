"""Keep mode switches and single-cue edits from rebuilding unrelated UI/data."""
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest
import shiboken6
from PySide6.QtCore import QEventLoop, QObject, QTimer, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance import visuals  # noqa: F401
from substance.backend import Backend
from substance.document import Cue, Document
from substance.media import ffmpeg_executable, process_options


@pytest.fixture
def backend(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    doc = Document()
    for i in range(20):
        cue = Cue(start=i * 4000, end=i * 4000 + 2000, text=f'Line {i}')
        doc.register_source(cue)
        doc.cues.append(cue)
    b._set_document(doc, '')
    yield b
    b.shutdown()


@pytest.fixture
def ui(backend):
    QQuickStyle.setStyle('Fusion')
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend', backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / 'substance/qml/Main.qml')))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    QTest.qWait(80)
    yield backend, window
    window.hide()
    shiboken6.delete(window)
    shiboken6.delete(engine)
    qInstallMessageHandler(previous)
    assert not [m for m in messages if any(s in m for s in ('ReferenceError', 'TypeError', 'Binding loop', 'Cannot assign', 'Unable to assign'))], messages


def test_mode_switch_reuses_surfaces_sink_and_keeps_drafts_and_undo(ui, monkeypatch):
    b, window = ui
    names = ('subtitleEditor', 'subtitleTable', 'videoOutput', 'audioWaveform')
    surfaces = {name: window.findChild(QObject, name) for name in names}
    assert all(surfaces.values())
    sink = b.media_controller._sink
    renderer = window.findChild(visuals.AssOverlay).renderer
    sinks = []
    monkeypatch.setattr(b.media_controller.player, 'setVideoSink', sinks.append)
    editor = surfaces['subtitleEditor']
    editor.setProperty('text', 'Original changed before switching')
    for mode in ('translation', 'timing', 'translation', 'timing'):
        b.setMode(mode)
        QTest.qWait(40)
        for name, surface in surfaces.items():
            assert window.findChildren(QObject, name) == [surface]
            assert surface.isVisible()
        assert editor.property('activeFocus')
        assert b.media_controller._sink is sink
        assert window.findChild(visuals.AssOverlay).renderer is renderer
        if mode == 'translation':
            editor.setProperty('text', 'Перевод без ожидания автоприменения')
    assert not sinks
    assert b.editor.document.cues[0].text == 'Original changed before switching'
    assert b.editor.document.cues[0].translation == 'Перевод без ожидания автоприменения'
    assert editor.property('text') == 'Перевод без ожидания автоприменения'
    b.undo()
    assert b.editor.document.cues[0].translation is None
    assert editor.property('text') == 'Original changed before switching'
    b.undo()
    assert editor.property('text') == 'Line 0'


def test_invalid_timing_draft_blocks_mode_switch_and_keeps_editor(ui):
    b, window = ui
    editor = window.findChild(QObject, 'subtitleEditor')
    b.stage('start', 'unfinished time')
    b.setMode('translation')
    QTest.qWait(30)
    assert b.mode == 'timing'
    assert b.draft['start'] == 'unfinished time'
    assert window.findChild(QObject, 'subtitleEditor') is editor


def test_mode_switch_keeps_playing_video_and_delivering_frames(ui, tmp_path):
    b, window = ui
    video = tmp_path / 'switch.mp4'
    subprocess.run([ffmpeg_executable(), '-nostdin', '-v', 'error', '-f', 'lavfi',
                    '-i', 'testsrc2=size=320x180:rate=24:duration=4', '-c:v', 'libx264',
                    '-y', str(video)], check=True, timeout=30, **process_options())

    def wait(ms):
        # Let the render thread acquire the GIL for Python-painted items.
        loop = QEventLoop()
        QTimer.singleShot(ms, loop.quit)
        loop.exec()

    media = b.media_controller
    media.player.setAudioOutput(None)
    b.openMediaPath(str(video))
    for _ in range(100):
        wait(20)
        if media._sink.videoFrame().isValid():
            break
    sink = media._sink
    assert sink.videoFrame().isValid()
    frames = []
    sink.videoFrameChanged.connect(lambda frame: frames.append(frame.startTime()))
    media.toggle()
    wait(150)
    for mode in ('translation', 'timing', 'translation', 'timing'):
        before_position, before_frames = media.position, len(frames)
        b.setMode(mode)
        wait(120)
        assert media.playing and media.position > before_position
        assert media._sink is sink and len(frames) > before_frames
        assert not window.grabWindow().isNull()
    media.toggle()


def test_edit_updates_changed_rows_without_reset_and_undo_restores_selection(backend):
    b = backend
    resets, updates = [], []
    b.model.modelReset.connect(lambda: resets.append(True))
    b.model.dataChanged.connect(lambda first, last, roles: updates.extend(range(first.row(), last.row() + 1)))
    before = list(b.model.cache)
    b.select(7)
    updates.clear()
    b.stage('text', 'Updated line')
    assert b.flush()
    assert not resets and updates == [7]
    assert b.model.cache[7]['cueText'] == 'Updated line'
    assert all(b.model.cache[i] is before[i] for i in range(20) if i != 7)
    assert b.model.cache[7]['selected'] and not b.model.cache[0]['selected']
    b.undo()
    assert not resets and b.model.cache[7]['cueText'] == 'Line 7'
    assert [row['selected'] for row in b.model.cache] == [i == 7 for i in range(20)]
    # Returning to the selection stored in the original row cache must not reuse
    # the intervening selection flags.
    b.select(0)
    b._refresh()
    assert [row['selected'] for row in b.model.cache] == [i == 0 for i in range(20)]


def test_timing_change_updates_previous_overlap_warning(backend):
    b = backend
    b.select(1)
    b.stage('start', '00:00:01.000')
    assert b.flush()
    assert b.model.cache[0]['warning']
    assert 'Пересечение' in b.model.cache[0]['issues']
    b.undo()
    assert not b.model.cache[0]['warning']


def test_filtered_edit_removes_row_and_undo_returns_it(backend):
    b = backend
    b.setSearch('Line 7', False, False)
    assert b.model.visible == [7]
    b.select(7)
    b.stage('text', 'Different')
    assert b.flush()
    # Search includes the immutable original too; use warnings to test membership.
    b.setSearch('', False, False)
    b.setFilter('warnings')
    assert not b.model.visible
    b.stage('text', 'x' * 100)
    assert b.flush()
    assert b.model.visible == [7]
    b.undo()
    assert not b.model.visible


def test_preview_draft_does_not_copy_or_mutate_project_assets(backend, monkeypatch):
    b = backend
    # Non-text project assets must never be copied while previewing one cue.
    class NoCopy(dict):
        def __deepcopy__(self, memo):
            raise AssertionError('Preview copied project assets')
    doc = b.editor.document
    doc.images = NoCopy({'portrait': 'encoded image payload'})
    before = deepcopy(doc.cues)
    signals = []
    b.previewChanged.connect(lambda: signals.append(True))
    b.stage('text', 'Draft preview')
    b._update_preview()
    assert 'Draft preview' in b.previewScript
    assert doc.cues == before
    assert b.editor.document is doc
    assert not b.canUndo
    b._update_preview()
    assert len(signals) == 1
    b.draft.clear()
    b._update_preview()
    assert 'Draft preview' not in b.previewScript
    assert len(signals) == 2
