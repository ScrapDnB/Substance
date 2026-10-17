from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
import hashlib
import threading

import pytest

from substance import speech, transcription as asr
from substance.backend import Backend
from substance.document import Cue, Document, save_document, load_document
from substance.transcription import SpeechModel, parse_segment, wrap_subtitle


@pytest.mark.parametrize('line, expected', [
    ('[00:00:01.250 --> 00:00:03.500]  Hello world.', (2250, 4500, 'Hello world.')),
    ('[00:00:01,250 --> 00:00:09,500] Привет', (2250, 5000, 'Привет')),
    ('[12:01:00.000 --> 12:01:01.000] Past the range', None),
    ('whisper_print_progress_callback: progress = 20%', None),
    ('[00:00:00.000 --> 00:00:00.000] zero', None),
    ('[00:00:00.000 --> 00:00:01.000] ', None),
])
def test_parse_stream_segments_and_clip_to_selected_range(line, expected):
    result = parse_segment(line, 1000, 5000, 42)
    assert (None if result is None else (result['start'], result['end'], result['text'])) == expected


def test_wrap_multilingual_and_cjk_without_losing_text():
    for value in ['Привет мир, это проверка длинной строки.', '日本語の音声から字幕を自動で作成します。', 'A   few words\n with whitespace.']:
        wrapped = wrap_subtitle(value, 10)
        assert all(len(line) <= 10 for line in wrapped.split(r'\N'))
        assert wrapped.replace(r'\N', '').replace(' ', '') == ''.join(value.split())


def toy_model(data=b'model content'):
    return SpeechModel('test', 'Test model', len(data), hashlib.sha256(data).hexdigest())


@contextmanager
def response(data):
    yield BytesIO(data)


def test_download_verifies_and_installs_atomically(tmp_path, monkeypatch):
    data = b'valid model'
    model = toy_model(data)
    monkeypatch.setattr(asr.urllib.request, 'urlopen', lambda *a, **k: response(data))
    job = asr.ModelDownload(model, tmp_path)
    result = []
    job.signals.finished.connect(result.append)
    job.run()
    assert result == [{'error': '', 'cancelled': False}]
    assert (tmp_path / model.filename).read_bytes() == data
    assert not list(tmp_path.glob('*.part'))


@pytest.mark.parametrize('data', [b'bad', b'wrong content', b'too many bytes returned'])
def test_failed_download_never_replaces_existing_model(tmp_path, monkeypatch, data):
    model = toy_model()
    target = tmp_path / model.filename
    target.write_bytes(b'existing copy')
    monkeypatch.setattr(asr.urllib.request, 'urlopen', lambda *a, **k: response(data))
    job = asr.ModelDownload(model, tmp_path)
    result = []
    job.signals.finished.connect(result.append)
    job.run()
    assert result[0]['error']
    assert target.read_bytes() == b'existing copy'
    assert not list(tmp_path.glob('*.part'))


def test_cancel_download_cleans_partial_file(tmp_path, monkeypatch):
    data = b'small model'
    model = toy_model(data)
    job = asr.ModelDownload(model, tmp_path)
    class CancellingResponse(BytesIO):
        def read(self, count):
            block = super().read(count)
            job.cancel()
            return block
    monkeypatch.setattr(asr.urllib.request, 'urlopen', lambda *a, **k: CancellingResponse(data))
    result = []
    job.signals.finished.connect(result.append)
    job.run()
    assert result == [{'error': '', 'cancelled': True}]
    assert list(tmp_path.iterdir()) == []


def test_local_model_is_rechecked_before_use(tmp_path):
    data = b'model content'
    model = toy_model(data)
    target = tmp_path / model.filename
    target.write_bytes(data)
    asr.verify_model(target, model, threading.Event())
    target.write_bytes(b'X' * model.size)
    with pytest.raises(ValueError, match='сумма'):
        asr.verify_model(target, model, threading.Event())


class DummyJob:
    def __init__(self, *a):
        self.signals = asr.SpeechSignals()
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path))
    backend = Backend()
    cue = Cue(text='Existing', original='Existing')
    document = Document(cues=[cue])
    document.register_source(cue)
    backend._set_document(document, '')
    backend.speech.directory.mkdir()
    model = toy_model()
    (backend.speech.directory / model.filename).write_bytes(b'X' * model.size)
    monkeypatch.setattr(speech, 'MODEL_BY_ID', {'test': model})
    monkeypatch.setattr(speech, 'whisper_executable', lambda: '/fake/whisper-cli')
    monkeypatch.setattr(speech, 'TranscriptionJob', DummyJob)
    monkeypatch.setattr(speech, 'QThreadPool', SimpleNamespace(globalInstance=lambda: SimpleNamespace(start=lambda job: None)))
    media = backend.media_controller
    media.path = str(tmp_path / 'audio.wav')
    Path(media.path).write_bytes(b'audio')
    monkeypatch.setattr(type(media), 'duration', property(lambda self: 10000))
    monkeypatch.setattr(type(media), 'audioTracks', property(lambda self: ['First', 'Second']))
    yield backend
    backend.shutdown()


def start(backend, **options):
    config = {'model': 'test', 'language': 'en', 'track': 1, 'start': '00:00:01.000', 'width': 42}
    config.update(options)
    return backend.speech.start(config)


def append(backend, text='Recognized speech', start=1000):
    backend.speech._task.signals.segment.emit({'text': text, 'start': start, 'end': start + 1000})
    backend.speech._flush_segments()


def finish(backend, error='', cancelled=False):
    backend.speech._task.signals.finished.emit({'error': error, 'cancelled': cancelled})


def test_streaming_append_preserves_manual_draft_selection_and_model(bridge):
    backend = bridge
    assert start(backend)
    backend.stage('text', 'Manual typing in progress')
    current_changes, resets, inserts = [], [], []
    backend.currentChanged.connect(lambda: current_changes.append(True))
    backend.model.modelReset.connect(lambda: resets.append(True))
    backend.model.rowsInserted.connect(lambda *a: inserts.append(True))
    append(backend)
    assert backend.count == 2
    assert backend.currentIndex == 0 and backend.selection == {0}
    assert backend.draft['text'] == 'Manual typing in progress'
    assert not current_changes and not resets and inserts == [True]
    finish(backend)
    assert backend.flush()
    assert backend.editor.document.cues[0].text == 'Manual typing in progress'
    assert backend.editor.document.cues[1].text == 'Recognized speech'


def test_adjacent_batches_share_one_undo_but_manual_edits_are_separate(bridge):
    assert start(bridge)
    append(bridge, 'One')
    append(bridge, 'Two', 2000)
    assert len(bridge.editor.undo_stack) == 1
    bridge.editor.update(0, text='Manual')
    append(bridge, 'Three', 3000)
    assert len(bridge.editor.undo_stack) == 3
    finish(bridge)
    bridge.undo()
    assert [cue.text for cue in bridge.editor.document.cues] == ['Manual', 'One', 'Two']


def test_save_boundary_is_not_coalesced(bridge):
    assert start(bridge)
    append(bridge, 'One')
    bridge.editor.mark_saved()
    append(bridge, 'Two', 2000)
    finish(bridge)
    assert len(bridge.editor.undo_stack) == 2
    bridge.undo()
    assert not bridge.editor.dirty


def test_stop_keeps_completed_segments_and_accepts_queued_ones(bridge):
    assert start(bridge)
    job = bridge.speech._task
    append(bridge)
    bridge.speech.stop()
    assert job.cancelled and bridge.speech.stopping
    job.signals.segment.emit({'text': 'Already completed', 'start': 2500, 'end': 3000})
    finish(bridge, cancelled=True)
    assert bridge.count == 3 and not bridge.speech.running
    assert 'Остановлено' in bridge.speech.status


def test_discard_keeps_user_edits_and_can_itself_be_undone(bridge):
    assert start(bridge)
    append(bridge, 'Keep this')
    append(bridge, 'Remove this', 2000)
    finish(bridge)
    bridge.editor.update(1, text='Manually corrected')
    bridge.speech.discard()
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'Manually corrected']
    bridge.undo()
    assert bridge.count == 3


def test_split_machine_cue_is_retained_by_selective_discard(bridge):
    assert start(bridge)
    append(bridge, 'Split this sentence')
    append(bridge, 'Unchanged', 3000)
    finish(bridge)
    bridge.editor.split(1, 5, 1500)
    bridge.speech.discard()
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'Split', 'this sentence']


def test_streaming_into_empty_document_selects_first_cue_only(bridge):
    bridge._set_document(Document(), '')
    assert start(bridge)
    append(bridge)
    assert bridge.currentIndex == 0 and bridge.selection == {0}
    append(bridge, 'Second', 3000)
    assert bridge.currentIndex == 0
    finish(bridge)


def test_stale_worker_cannot_write_into_new_document(bridge):
    assert start(bridge)
    old = bridge.speech._task
    bridge._set_document(Document(), '')
    old.signals.segment.emit({'text': 'Stale', 'start': 0, 'end': 1000})
    old.signals.finished.emit({'error': '', 'cancelled': True})
    bridge.speech._flush_segments()
    assert bridge.count == 0 and old.cancelled


def test_document_switch_is_blocked_during_recognition(bridge):
    assert start(bridge)
    editor = bridge.editor
    bridge.newDocument()
    assert bridge.editor is editor
    assert 'остановите' in bridge.message
    finish(bridge)


def test_close_drains_completed_batch_and_saves_before_detaching(bridge, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    assert start(bridge)
    job = bridge.speech._task
    job.signals.segment.emit({'text': 'Ready before closing', 'start': 1000, 'end': 2000})
    path = tmp_path / 'saved.substance'
    bridge.path = str(path)
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.StandardButton.Save)
    assert bridge.requestClose()
    assert job.cancelled and not bridge.speech.running
    assert load_document(path).cues[-1].text == 'Ready before closing'


def test_partial_error_keeps_valid_cues(bridge):
    assert start(bridge)
    append(bridge)
    finish(bridge, error='Out of memory')
    assert bridge.count == 2 and bridge.speech.error
    assert 'Out of memory' in bridge.speech.status


def test_error_before_first_cue_stays_visible_in_main_window(bridge):
    assert start(bridge)
    finish(bridge, error='GPU unavailable')
    assert bridge.speech.statusVisible and bridge.speech.error
    bridge.speech.dismiss()
    assert not bridge.speech.statusVisible


def test_protected_online_original_is_rejected_before_recognition(bridge):
    bridge.online.repository = SimpleNamespace(snapshot={'metadata': {}}, pending=None)
    try:
        assert not bridge.speech.canAppend
        assert not start(bridge)
        assert 'неизменяем' in bridge.speech.status
        assert bridge.count == 1
    finally:
        bridge.online.repository = None


def test_incoming_segments_are_not_appended_after_shutdown(bridge):
    assert start(bridge)
    old = bridge.speech._task
    bridge.speech.shutdown()
    old.signals.segment.emit({'text': 'Stale after close', 'start': 0, 'end': 1000})
    bridge.speech._flush_segments()
    assert bridge.count == 1


@pytest.mark.parametrize('options', [
    {'track': -1}, {'track': 2}, {'start': '00:00:12.000'}, {'end': '00:00:01.000'},
    {'width': 10}, {'language': 'no-such-language'}, {'model': 'unknown'}, {'start': 'broken'}
])
def test_invalid_options_do_not_start_worker(bridge, options):
    assert not start(bridge, **options)
    assert not bridge.speech.running and bridge.speech.error
    assert bridge.count == 1


def test_reading_timing_settings_are_saved_and_loaded(bridge):
    assert start(bridge, timing={'reading_cps': 20, 'max_hold_ms': 1000, 'lead_ms': 50})
    assert bridge.speech.timing['reading_cps'] == 20
    assert bridge.speech.timing['max_hold_ms'] == 1000
    assert bridge.speech.timing['lead_ms'] == 50
    finish(bridge)


def test_invalid_timing_settings_do_not_start_or_replace_document(bridge):
    assert not start(bridge, timing={'reading_cps': 0}, newDocument=True)
    assert bridge.count == 1 and not bridge.speech.running


def test_completed_subtitles_roundtrip_as_ass_and_project(bridge, tmp_path):
    assert start(bridge)
    append(bridge, 'Recognized\\Nsubtitle')
    finish(bridge)
    for suffix in ('.ass', '.substance'):
        path = tmp_path / ('result' + suffix)
        save_document(bridge.editor.document, path)
        restored = load_document(path)
        assert [cue.text for cue in restored.cues] == ['Existing', 'Recognized\\Nsubtitle']
        assert restored.cues[1].start == 1000 and restored.cues[1].end == 2000


def first_pass(backend):
    assert start(backend)
    append(backend, 'First version', 1000)
    append(backend, 'Second phrase', 3000)
    finish(backend)
    return [cue.id for cue in backend.editor.document.cues]


def test_repeat_updates_result_atomically_without_a_second_copy(bridge):
    previous = first_pass(bridge)
    assert start(bridge)
    append(bridge, 'Improved first version', 1000)
    assert [cue.id for cue in bridge.editor.document.cues] == previous
    append(bridge, 'Improved second phrase', 3000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'Improved first version', 'Improved second phrase']
    assert all(cue.id not in previous[1:] for cue in bridge.editor.document.cues)
    assert start(bridge)
    append(bridge, 'Third pass', 1000)
    append(bridge, 'Third second phrase', 3000)
    finish(bridge)
    assert bridge.count == 3


def test_repeat_preserves_manual_edits_and_skips_overlapping_new_phrases(bridge):
    first_pass(bridge)
    bridge.editor.update(1, text='My manual correction')
    assert start(bridge)
    append(bridge, 'Machine would replace my edit', 1000)
    append(bridge, 'New second phrase', 3000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'My manual correction', 'New second phrase']


def test_manual_draft_typed_during_repeat_is_preserved(bridge):
    first_pass(bridge)
    assert start(bridge)
    bridge.select(1, 0)
    bridge.stage('text', 'Typed during recognition')
    append(bridge, 'New first phrase', 1000)
    append(bridge, 'New second phrase', 3000)
    assert bridge.draft['text'] == 'Typed during recognition'
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'Typed during recognition', 'New second phrase']
    assert bridge.current['editText'] == 'Typed during recognition'


@pytest.mark.parametrize('suffix', ['.substance', '.ass'])
def test_repeat_after_save_and_reopen_uses_durable_origin(bridge, tmp_path, suffix):
    first_pass(bridge)
    path = tmp_path / ('repeat' + suffix)
    save_document(bridge.editor.document, path)
    bridge._set_document(load_document(path), str(path))
    assert start(bridge)
    append(bridge, 'Updated after reopening', 1000)
    append(bridge, 'Updated second', 3000)
    finish(bridge)
    assert bridge.count == 3
    assert bridge.editor.document.cues[1].text == 'Updated after reopening'


@pytest.mark.parametrize('result', [{'cancelled': True}, {'error': 'GPU failed'}, {}])
def test_cancel_error_and_empty_repeat_keep_previous_result(bridge, result):
    first_pass(bridge)
    previous = bridge.editor.document.to_dict()
    assert start(bridge)
    if result:
        append(bridge, 'Partial new result', 1000)
    finish(bridge, **result)
    assert bridge.editor.document.to_dict() == previous
    assert bridge.speech.canDiscard


def test_repeat_undo_and_redo_restore_whole_result_in_one_operation(bridge):
    first_pass(bridge)
    previous = bridge.editor.document.to_dict()
    assert start(bridge)
    append(bridge, 'Updated', 1000)
    append(bridge, 'Updated second', 3000)
    finish(bridge)
    updated = bridge.editor.document.to_dict()
    bridge.undo()
    assert bridge.editor.document.to_dict() == previous
    bridge.redo()
    assert bridge.editor.document.to_dict() == updated


def test_discard_repeat_restores_old_result(bridge):
    first_pass(bridge)
    previous = [cue.id for cue in bridge.editor.document.cues]
    assert start(bridge)
    append(bridge, 'Updated', 1000)
    append(bridge, 'Updated second', 3000)
    finish(bridge)
    bridge.speech.discard()
    assert [cue.id for cue in bridge.editor.document.cues] == previous


def test_discard_repeat_retains_manual_new_cue_and_restores_other_old_cues(bridge):
    first_pass(bridge)
    assert start(bridge)
    append(bridge, 'Updated', 1000)
    append(bridge, 'Updated second', 3000)
    finish(bridge)
    bridge.editor.update(1, text='Corrected new result')
    bridge.speech.discard()
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'Corrected new result', 'Second phrase']


def test_repeat_selected_range_preserves_rest_of_recognition(bridge):
    first_pass(bridge)
    assert start(bridge, end='00:00:02.000')
    append(bridge, 'Updated only here', 1000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'Updated only here', 'Second phrase']


def test_different_audio_track_does_not_replace_previous_track(bridge):
    first_pass(bridge)
    assert start(bridge, track=0)
    append(bridge, 'Another track', 1000)
    finish(bridge)
    assert bridge.count == 4
    assert bridge.editor.document.cues[1].text == 'First version'


def test_repeat_preserves_split_and_merged_manual_descendants(bridge):
    first_pass(bridge)
    bridge.editor.split(1, 5, 1500)
    assert start(bridge)
    append(bridge, 'Would duplicate split phrase', 1000)
    append(bridge, 'New second', 3000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'First', 'version', 'New second']


def test_legacy_unknown_result_is_preserved_without_creating_an_overlap(bridge):
    from substance.document import identity
    cue = Cue(start=1000, end=2000, text='Old version or user edit', original='Old version or user edit',
              extras={'transcription_session': identity('old')})
    def add(document):
        document.register_source(cue)
        document.cues.append(cue)
    bridge.editor.transact('Legacy result', add)
    bridge._refresh()
    assert start(bridge)
    append(bridge, 'Duplicate', 1000)
    finish(bridge)
    assert bridge.count == 2
    assert bridge.editor.document.cues[-1].text == 'Old version or user edit'


def test_repeat_keeps_protected_middle_phrase_in_time_order(bridge):
    first_pass(bridge)
    assert start(bridge)
    append(bridge, 'One', 1000)
    append(bridge, 'Two', 3000)
    append(bridge, 'Three', 5000)
    finish(bridge)
    bridge.editor.update(2, text='My middle phrase')
    assert start(bridge)
    append(bridge, 'New one', 1000)
    append(bridge, 'New two', 3000)
    append(bridge, 'New three', 5000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'New one', 'My middle phrase', 'New three']


def test_discard_repeat_does_not_restore_old_cue_over_retimed_manual_edit(bridge):
    first_pass(bridge)
    assert start(bridge)
    append(bridge, 'Updated', 1000)
    append(bridge, 'Updated second', 3000)
    finish(bridge)
    bridge.editor.update(1, start=7000, end=8000)
    bridge.speech.discard()
    assert sorted(cue.text for cue in bridge.editor.document.cues) == sorted(['Existing', 'Second phrase', 'Updated'])
    assert sum(cue.text in ('First version', 'Updated') for cue in bridge.editor.document.cues) == 1


def test_repeat_preserves_reviewed_cue(bridge):
    from substance.project import ReviewEntry
    first_pass(bridge)
    cue_id = bridge.editor.document.cues[1].id
    bridge.editor.transact('Review', lambda document: document.reviews.append(ReviewEntry(id='review_1', cue_ids=[cue_id], text='Check this')))
    assert start(bridge)
    append(bridge, 'Would orphan review', 1000)
    append(bridge, 'New second phrase', 3000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'First version', 'New second phrase']
    assert bridge.editor.document.reviews[0].cue_ids == [cue_id]


def test_skipping_coarse_phrase_over_manual_edit_does_not_erase_its_other_words(bridge):
    first_pass(bridge)
    bridge.editor.update(1, text='My correction')
    assert start(bridge)
    bridge.speech._task.signals.segment.emit({'text': 'A coarser phrase spanning both old lines', 'start': 1000, 'end': 4000})
    append(bridge, 'New later phrase', 5000)
    finish(bridge)
    assert [cue.text for cue in bridge.editor.document.cues] == ['Existing', 'My correction', 'Second phrase', 'New later phrase']


def test_provenance_does_not_include_device_local_path(bridge):
    import json
    first_pass(bridge)
    document = bridge.editor.document
    assert bridge.media_controller.path not in json.dumps([cue.extras for cue in document.cues])
    assert bridge.media_controller.path not in json.dumps(document.source_lines)


def test_invalid_time_draft_blocks_repeat_application_without_losing_old_result(bridge):
    first_pass(bridge)
    previous = bridge.editor.document.to_dict()
    assert start(bridge)
    bridge.select(1, 0)
    bridge.stage('start', 'invalid time')
    append(bridge, 'New first', 1000)
    finish(bridge)
    assert bridge.editor.document.to_dict() == previous
    assert bridge.draft['start'] == 'invalid time'
    assert bridge.speech.error
