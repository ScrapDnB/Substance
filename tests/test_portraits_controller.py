from copy import deepcopy

import pytest
from PySide6.QtGui import QImage

from substance.backend import Backend
from substance.document import Cue, Document, load_document
from substance.images import encode_image


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path / 'data'))
    b = Backend()
    video = tmp_path / 'movie.mp4'
    video.write_bytes(b'fixture')
    doc = Document(cues=[Cue(start=0, end=1000, character='Alice', text='Hello'),
                         Cue(start=11000, end=12000, character='Bob', text='World')])
    doc.media['path'] = str(video)
    b._set_document(doc, str(tmp_path / 'project.substance'))
    b.media_controller.path = str(video)
    yield b
    b.shutdown()


def ready(b):
    p = b.portraits
    p._context = p._media_context()
    p._snapshot = deepcopy(b.editor.document)
    image = QImage(128, 96, QImage.Format.Format_RGB32)
    image.fill('green')
    candidate = {'source': encode_image(image, source=True)[1], 'preview': image,
                 'crop': [.1, .1, .6, .8], 'time': 500, 'quality': 1}
    p._rows = [{'cardId': c.id, 'checked': True, 'confident': True, 'reason': '',
                'appearances': 4, 'candidates': [candidate], 'variant': 0, 'applied': False} for c in b.editor.document.characters]
    return p


def wait_save(p):
    from PySide6.QtCore import QEventLoop, QTimer
    for _ in range(300):
        if not p.busy:
            return
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    pytest.fail('Portrait save did not finish')


def test_batch_is_one_undo_and_survives_project_save(bridge, tmp_path):
    b = bridge
    p = ready(b)
    before = deepcopy(b.editor.document)
    assert p.canApply and p.apply(False)
    assert p.adding and p.saveVisible
    wait_save(p)
    assert all(len(c.portraits) == 1 and c.primary for c in b.editor.document.characters)
    assert len(b.editor.undo_stack) == 1
    assert p.saveProgress == 1 and '2 из 2' in p.saveStatus
    assert b.save()
    assert load_document(b.path).images == b.editor.document.images
    b.undo()
    assert b.editor.document == before
    assert p.stale


def test_document_or_video_change_blocks_old_results(bridge):
    b = bridge
    p = ready(b)
    b.editor.update(0, text='Changed')
    assert p.stale and not p.apply(False)
    p = ready(b)
    from pathlib import Path
    Path(b.media_controller.path).write_bytes(b'new video data')
    assert p.stale and not p.apply(False)


def test_preserves_existing_primary_unless_requested(bridge):
    b = bridge
    p = ready(b)
    assert p.apply(False)
    wait_save(p)
    primary = b.editor.document.characters[0].primary
    p = ready(b)
    assert p.apply(False)
    wait_save(p)
    assert b.editor.document.characters[0].primary == primary
    assert len(b.editor.document.characters[0].portraits) == 2
    assert 'галерею' in p.saveStatus
    p = ready(b)
    assert p.apply(True)
    wait_save(p)
    assert b.editor.document.characters[0].primary != primary


def test_unnamed_filter_keeps_source_indices_and_manual_assignment_merges_variants(bridge):
    p = ready(bridge)
    p._rows.insert(0, {**p._rows[0], 'cardId': '', 'checked': False})
    p._rows[0]['candidates'] = [{**p._rows[0]['candidates'][0], 'crop': [.2, .2, .5, .6]}]
    model = p.resultsModel
    assert not p.showUnnamed and model.rowCount() == 2
    assert model.data(model.index(0, 0), model.PORTRAIT)['sourceIndex'] == 1
    p.check(1, False)
    assert not p._rows[1]['checked']
    p.setShowUnnamed(True)
    assert model.rowCount() == 3 and p.summary['unnamed'] == 1
    p.assign(0, p._rows[1]['cardId'])
    assert model.rowCount() == 2 and p.summary['unnamed'] == 0
    assert len(p._rows[1]['candidates']) == 2
    assert p._rows[1]['variant'] == 0 and p._rows[1]['checked']
    assert p.visibleIndex(0) == -1 and p.visibleIndex(1) == 0
    assert p.apply(False)
    wait_save(p)
    assert len(bridge.editor.document.characters[0].portraits) == 1
    p.nextVariant(1)
    assert not p._rows[1]['applied']
    p.check(1, True)
    assert p.apply(False)
    wait_save(p)
    assert len(bridge.editor.document.characters[0].portraits) == 2
    p.nextVariant(1)
    assert p._rows[1]['applied'] and not p._rows[1]['checked']


@pytest.mark.parametrize('action', ['cancel', 'edit', 'error'])
def test_background_preparation_failure_cancellation_and_stale_document_are_visible(bridge, monkeypatch, action):
    from substance.portrait_job import PreparePortraitsJob
    p = ready(bridge)
    if action == 'error':
        def fail(job):
            raise ValueError('test preparation failure')
        monkeypatch.setattr(PreparePortraitsJob, 'execute', fail)
    assert p.apply(False)
    if action == 'cancel':
        p.cancel()
    elif action == 'edit':
        bridge.editor.update(0, text='Changed during preparation')
    wait_save(p)
    assert not bridge.editor.document.images
    assert p.saveVisible and p.saveProgress < 1
    assert {'cancel': 'отменено', 'edit': 'изменились', 'error': 'test preparation failure'}[action] in p.saveStatus


def test_fast_mode_is_passed_to_worker_and_cannot_change_during_search(bridge, monkeypatch):
    from substance.portrait_analysis import ANALYSIS_PROFILES
    from substance.portrait_job import PortraitJob
    p = bridge.portraits
    p.setSpeed('fast')
    assert p.speed == 'fast'
    assert bridge.settings.value('portraits/speed') == 'fast'
    profiles = []
    monkeypatch.setattr(bridge.media_controller.player, 'hasVideo', lambda: True)
    def execute(job):
        profiles.append(job.profile)
        job.signals.result.emit({'rows': [], 'frames': 0})
    monkeypatch.setattr(PortraitJob, 'execute', execute)
    p.analyze()
    p.setSpeed('normal')
    assert p.speed == 'fast'
    wait_save(p)
    assert profiles == [ANALYSIS_PROFILES['fast']]
    p.setSpeed('normal')
    assert p.speed == 'normal'


def test_cancel_after_worker_finishes_but_before_gui_commit(bridge, monkeypatch):
    import threading
    from PySide6.QtCore import Qt
    from substance.portrait_job import PreparePortraitsJob
    finished = threading.Event()
    original = PreparePortraitsJob.execute
    def execute(job):
        job.signals.finished.connect(lambda _: finished.set(), Qt.ConnectionType.DirectConnection)
        original(job)
    monkeypatch.setattr(PreparePortraitsJob, 'execute', execute)
    p = ready(bridge)
    assert p.apply(False)
    assert finished.wait(2)
    p.cancel()
    wait_save(p)
    assert not bridge.editor.document.images
    assert 'отменено' in p.saveStatus


def test_duplicate_recipients_require_explicit_resolution(bridge):
    p = ready(bridge)
    p._rows[1]['cardId'] = p._rows[0]['cardId']
    assert not p.apply(False)
    assert not bridge.editor.document.images


def test_new_character_is_created_with_portrait_in_one_undo_without_invalidating_results(bridge):
    p = ready(bridge)
    before = deepcopy(bridge.editor.document)
    assert not p.createCharacter(0, '   ')
    assert p.createCharacter(0, '  New Hero  ')
    assert not p.stale and bridge.editor.document == before
    assert p.rows[0]['cardName'] == 'New Hero' and p.rows[0]['newCharacter']
    assert p.createCharacter(1, 'new hero')
    assert p.summary['found'] == 1 and len(p._new_characters) == 1
    assert p.apply(False)
    wait_save(p)
    card = next(c for c in bridge.editor.document.characters if c.name == 'New Hero')
    assert card.primary and len(card.portraits) == 1
    assert not p.stale and not p._new_characters
    bridge.undo()
    assert bridge.editor.document == before


def test_old_worker_results_and_preview_keys_are_ignored(bridge):
    p = ready(bridge)
    old = p._generation
    old_url = p.rows[0]['url'].split('/')[-1]
    assert not p.preview_image(old_url).isNull()
    p.reset()
    p._on_result(old, {'rows': ['old'], 'frames': 4})
    p._on_finished(old, {'cancelled': False, 'error': 'old error'})
    assert not p.rows and not p.status
    assert p.preview_image(old_url).isNull()


def test_worker_results_are_delivered_on_gui_thread(bridge, monkeypatch, qt_application):
    from PySide6.QtCore import QThread, QEventLoop, QTimer
    from substance.portrait_job import PortraitJob
    b = bridge
    p = b.portraits
    monkeypatch.setattr(b.media_controller.player, 'hasVideo', lambda: True)
    delivery = []
    original = p._on_result
    def receive(token, result):
        delivery.append(QThread.currentThread() == qt_application.thread())
        original(token, result)
    monkeypatch.setattr(p, '_on_result', receive)
    monkeypatch.setattr(PortraitJob, 'execute', lambda job: job.signals.result.emit({'rows': [], 'frames': 2}))
    p.analyze()
    for _ in range(100):
        if not p.busy:
            break
        loop = QEventLoop()
        QTimer.singleShot(10, loop.quit)
        loop.exec()
    assert delivery == [True]
    assert not p.busy


def test_check_updates_only_one_row_without_resetting_results(bridge):
    from PySide6.QtTest import QSignalSpy
    p = ready(bridge)
    model = p.resultsModel
    resets = QSignalSpy(model.modelReset)
    updates = QSignalSpy(model.dataChanged)
    characters = QSignalSpy(p.charactersChanged)
    p.check(1, False)
    assert resets.count() == 0
    assert updates.count() == 1
    assert updates.at(0)[0].row() == updates.at(0)[1].row() == 1
    assert not model.data(model.index(1, 0), model.PORTRAIT)['checked']
    assert p.summary['selected'] == 1
    assert characters.count() == 0
    p._status = 'Progress changed'
    p.changed.emit()
    assert updates.count() == 1 and resets.count() == 0


def test_model_resets_only_for_new_analysis_and_keeps_full_preview(bridge):
    from PySide6.QtTest import QSignalSpy
    p = ready(bridge)
    p.setShowUnnamed(True)
    model = p.resultsModel
    resets = QSignalSpy(model.modelReset)
    detail = p.preview_image(p.rows[0]['detailUrl'].split('/')[-1])
    assert not detail.isNull() and detail.width() > 0
    p.assign(0, '')
    assert resets.count() == 0
    assert model.data(model.index(0, 0), model.PORTRAIT)['cardName'] == 'Персонаж не определён'
    p.reset()
    assert resets.count() == 1 and model.rowCount() == 0
