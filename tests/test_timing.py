from copy import deepcopy

import pytest

from substance.backend import Backend
from substance.document import Cue, Document
from substance.timing import point_mapping, timing_plan


def document():
    doc = Document()
    for start, end in [(1000, 2000), (11000, 13000), (21000, 23000), (31000, 33000)]:
        c = Cue(start=start, end=end, text=r'{\i1}Текст', original='Original', translation='Перевод', character='Alice', extras={'untimed': True, 'custom': 17})
        doc.register_source(c)
        doc.cues.append(c)
    return doc


def test_one_point_shifts_duration_and_multipt_maps_both_edges():
    cues = document().cues
    one = timing_plan(cues, range(4), points={cues[1].id: 12000})
    assert [(r['start'], r['end']) for r in one] == [(2000, 3000), (12000, 14000), (22000, 24000), (32000, 34000)]
    mapping = point_mapping(cues, {cues[0].id: 2000, cues[1].id: 22000, cues[2].id: 27000})
    assert [mapping(t) for t in [0, 1000, 6000, 11000, 13000, 21000, 31000]] == [0, 2000, 12000, 22000, 23000, 27000, 32000]
    # A cue straddling an anchor maps each edge through its own segment.
    cues[1].start, cues[1].end = 11000, 23000
    rows = timing_plan(cues, [1], points={cues[0].id: 2000, cues[1].id: 22000, cues[2].id: 27000})
    assert (rows[0]['start'], rows[0]['end']) == (22000, 28000)


@pytest.mark.parametrize('targets', [(3000, 2000), (3000, 3000)])
def test_reject_reversed_or_collapsed_points(targets):
    cues = document().cues
    with pytest.raises(ValueError, match='возрастать'):
        point_mapping(cues, {cues[0].id: targets[0], cues[1].id: targets[1]})


def test_duplicate_source_and_invalid_intervals():
    cues = document().cues
    cues[1].start = cues[0].start
    with pytest.raises(ValueError, match='одинаковое'):
        point_mapping(cues, {cues[0].id: 2000, cues[1].id: 3000})
    assert timing_plan(cues, [0], delta=-2000)[0]['error']
    assert timing_plan(cues, [0], delta=1001, edges='start')[0]['error']


@pytest.fixture
def backend(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    b = Backend()
    b._set_document(document(), '')
    yield b
    b.shutdown()


def test_shift_scopes_preview_cancel_atomic_undo_preserve_metadata(backend):
    b = backend
    b.select(1)
    b.selection = {1, 3}
    before = deepcopy(b.editor.document)
    t = b.timing
    b.openShift()
    assert t.scope == 'all' and t.affectedCount == 4 and not t.canApply
    t.setShift(500, 'both')
    assert b.editor.document == before and t.changedCount == 4
    t.cancel()
    assert b.editor.document == before and not b.canUndo
    b.openShift()
    t.setScope('selected')
    t.setShift(500, 'both')
    assert t.affectedCount == 2 and t.apply()
    assert [c.start for c in b.editor.document.cues] == [1000, 11500, 21000, 31500]
    assert b.editor.document.source_lines == before.source_lines
    assert b.editor.document.cues[1].extras == {'custom': 17}
    assert b.editor.document.cues[1].translation == before.cues[1].translation
    b.undo()
    assert b.editor.document == before
    b.redo()
    assert b.editor.document.cues[1].start == 11500
    b.openShift()
    t.setScope('following')
    assert t.affectedCount == 3
    t.setShift(100, 'end')
    assert t.apply()
    assert b.editor.document.cues[1].start == 11500 and b.editor.document.cues[1].end == 13600


def test_points_upsert_delete_and_validation(backend):
    b, t = backend, backend.timing
    b.openPointSync()
    assert not t.canApply
    assert not t.setPoint('bad')
    assert 'Таймкод' in t.error
    assert t.setPoint('00:00:02.000')
    assert t.changedCount == 4 and len(t.points) == 1
    assert t.setPoint('00:00:03.000') and len(t.points) == 1
    t.selectPreview(2)
    assert t.setPoint('00:00:25.000')
    assert t.preview['start'] == 25000
    before = deepcopy(b.editor.document)
    assert t.apply()
    b.undo()
    assert b.editor.document == before
    b.openPointSync()
    t.setPoint('00:00:00.000')
    t.selectPreview(2)
    t.setPoint('00:00:00.000')
    assert 'возрастать' in t.error and not t.canApply
    t.removePoint(2)
    assert not t.error and t.canApply


def test_invalid_shift_stale_draft_document_replacement_and_validator(backend):
    b, t = backend, backend.timing
    original = deepcopy(b.editor.document)
    b.openShift()
    t.setShift(-1500, 'both')
    assert not t.canApply and not t.apply() and 'раньше нуля' in t.error
    assert b.editor.document == original
    t.setShift(100, 'both')
    b.stage('start', '00:00:01.100')
    assert t.stale and not t.apply()
    b.draft.clear()
    b.editor.update(0, text='Изменение')
    b._refresh()
    assert t.stale and not t.apply()
    b.openShift()
    t.setShift(500, 'both')

    def deny(doc):
        raise ValueError('Нет права менять тайминг')

    b.editor.validator = deny
    assert not t.apply() and 'Нет права' in t.error
    assert b.editor.document.cues[0].start == 1000
    b._set_document(document(), '')
    assert not t.canApply and not t.rows


def test_media_metadata_and_audio_track_do_not_invalidate_timing(backend, monkeypatch):
    b, t = backend, backend.timing
    b.openPointSync()
    assert t.setPoint('00:00:02.000')
    b.editor.transact('Медиа', lambda d: (d.media.update(path='new.wav'), setattr(d, 'fps', 25)))
    b._refresh()
    assert not t.stale and t.canApply
    played = []
    monkeypatch.setattr(type(b.media_controller), 'hasMedia', property(lambda self: True))
    monkeypatch.setattr(b.media_controller, 'playRange', lambda *args: played.append(args))
    t.play(0, False)
    t.play(0, True)
    assert played == [(1000, 2000), (2000, 3000)]
    assert t.apply()
    assert b.editor.document.media['path'] == 'new.wav' and b.editor.document.fps == 25
