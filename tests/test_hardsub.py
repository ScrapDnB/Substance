from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np
import pytest
from PySide6.QtCore import QEventLoop, QThreadPool, QTimer

from substance.backend import Backend
from substance.document import Cue, Document, load_document, save_document
from substance.hardsub import HardsubJob, TextRuns, ass_text, engine_info, parse_tsv
from substance.media import ffmpeg_executable
from substance.tool_jobs import video_identity


def test_runs_vote_jitter_keep_blank_gaps_and_clip_last_interval():
    runs = TextRuns(250, 300)
    for stamp, text in [(0, 'Hello, world today!'), (250, 'Hello, world today!'),
                        (500, 'Hello, wor1d today!'), (750, ''),
                        (1000, 'Hello, world today!'), (1250, 'Hello, world today!'),
                        (1500, 'Different subtitle'), (1750, 'Different subtitle')]:
        runs.feed(stamp, min(1900, stamp + 250), text, .9, 'preview')
    runs.close()
    assert [(r['start'], r['end'], r['text']) for r in runs.rows] == [
        (0, 750, 'Hello, world today!'), (1000, 1500, 'Hello, world today!'),
        (1500, 1900, 'Different subtitle')]
    assert runs.rows[0]['preview'] == 'preview'


def test_short_noise_is_filtered_and_tsv_respects_lines_and_confidence():
    runs = TextRuns(250, 300)
    runs.feed(0, 250, 'Noise', .7)
    runs.feed(250, 500, '', 0)
    assert not runs.rows
    value = 'level\tblock_num\tpar_num\tline_num\tconf\ttext\n5\t1\t1\t1\t95\tHello\n5\t1\t1\t1\t90\tworld\n5\t1\t1\t2\t80\tAgain\n5\t1\t1\t2\t20\tNoise\n'
    text, score = parse_tsv(value, .6)
    assert text == 'Hello world\nAgain' and .8 < score < 1
    assert r'\p1' not in ass_text('{\\p1}\nHello')


def make_video(tmp_path):
    frames = []
    for i, text in enumerate(['', 'A burned in subtitle', 'A second subtitle', '']):
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        if text:
            cv2.putText(frame, text, (35, 305), cv2.FONT_HERSHEY_SIMPLEX, .95, (255, 255, 255), 2, cv2.LINE_AA)
        path = tmp_path / f'frame{i}.png'
        cv2.imwrite(str(path), frame)
        frames.append(path)
    manifest = tmp_path / 'frames.txt'
    manifest.write_text(''.join(f"file '{p}'\nduration 1\n" for p in frames) + f"file '{frames[-1]}'\n")
    video = tmp_path / 'hardsub.mp4'
    subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i',
                    str(manifest), '-r', '25', '-c:v', 'mpeg4', str(video)], check=True)
    return video


def test_real_video_sampling_preview_crops_and_cancellation(tmp_path, monkeypatch):
    path = make_video(tmp_path)
    options = {'step': 250, 'minimum': 300, 'region': [0, .7, 1, .3], 'language': 'eng', 'confidence': 60}
    job = HardsubJob(str(path), 0, 4000, options, {})
    images = []
    def recognize(frame):
        images.append(frame.shape)
        # Recognize presence independently from the grouping implementation.
        return ('Subtitle', .95) if np.max(frame) > 220 else ('', 0)
    monkeypatch.setattr(job, 'recognize', recognize)
    results = []
    job.signals.result.connect(results.append)
    job.execute()
    assert results[0]['identity'] == video_identity(path)
    assert results[0]['frames'] == 16 and len(images) == 16
    assert images[0] == (216, 1280, 3)
    assert len(results[0]['rows']) == 1
    row = results[0]['rows'][0]
    assert abs(row['start'] - 1000) <= 250 and abs(row['end'] - 3000) <= 250
    assert row['preview'].startswith('data:image/jpeg;base64,')
    preview = HardsubJob(str(path), 1000, 4000, options, {}, preview=True)
    preview.signals.result.connect(results.append)
    preview.execute()
    assert results[-1]['preview'].startswith('data:image/jpeg;base64,')
    cancelled = HardsubJob(str(path), 0, 4000, options, {})
    cancelled.cancel()
    cancelled.signals.result.connect(results.append)
    cancelled.run()
    assert len(results) == 2 and cancelled.decoder is None


@pytest.fixture
def bridge(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path / 'data'))
    b = Backend()
    path = tmp_path / 'video.mp4'
    path.write_bytes(b'test video identity')
    b.media_controller.path = str(path)
    monkeypatch.setattr(type(b.media_controller), 'hasVideo', property(lambda self: True))
    monkeypatch.setattr(type(b.media_controller), 'duration', property(lambda self: 10000))
    b.hardsub._info = {'engine': 'test', 'title': 'Test', 'languages': ['eng']}
    monkeypatch.setattr(QThreadPool, 'start', lambda self, job: None)
    yield b
    b.shutdown()


def complete(b, rows=None, error='', cancelled=False):
    job = b.hardsub._job
    if rows is not None:
        job.signals.result.emit({'identity': video_identity(b.media_controller.path), 'rows': rows, 'frames': 4})
    job.signals.finished.emit({'error': error, 'cancelled': cancelled})


def row(text='OCR text', start=1000, end=2000):
    return {'text': text, 'start': start, 'end': end, 'confidence': .95, 'checked': True, 'preview': ''}


def test_import_translation_source_save_undo_and_selection(bridge, tmp_path):
    b = bridge
    cue = Cue(start=3000, end=4000, text='Existing', original='Existing')
    doc = Document(cues=[cue])
    doc.register_source(cue)
    b._set_document(doc, '')
    b.select(0)
    before = deepcopy(b.editor.document)
    assert b.hardsub.analyze({'language': 'eng'})
    assert b.editor.document == before
    complete(b, [row(), row('Skip', 5000, 6000)])
    b.hardsub.check(1, False)
    assert b.hardsub.canApply
    assert b.hardsub.apply(True)
    assert b.mode == 'translation'
    assert b.currentIndex == 1 and b.selection == {1}
    added = b.editor.document.cues[0]
    assert added.original == 'OCR text' and added.translation == ''
    assert b.editor.document.source_lines[added.id]['text'] == 'OCR text'
    assert not b.hardsub.canApply and not b.hardsub.apply(True)
    for suffix in ('.ass', '.substance'):
        path = tmp_path / ('result' + suffix)
        save_document(b.editor.document, path)
        restored = load_document(path)
        assert restored.cues[0].original == 'OCR text'
        assert restored.cues[0].translation == ''
    b.undo()
    assert b.editor.document == before
    b.redo()
    assert b.count == 2


def test_repeat_import_skips_same_text_overlapping_time_only(bridge):
    b = bridge
    for _ in range(2):
        assert b.hardsub.analyze({})
        complete(b, [row()])
        b.hardsub.apply(False)
    assert b.count == 1
    assert b.hardsub.analyze({})
    complete(b, [row(start=3000, end=4000)])
    assert b.hardsub.apply(False)
    assert b.count == 2


@pytest.mark.parametrize('mutation', ['document', 'video', 'replace', 'draft'])
def test_stale_result_cannot_be_applied(bridge, mutation):
    b = bridge
    assert b.hardsub.analyze({})
    complete(b, [row()])
    if mutation == 'document':
        b.editor.transact('Manual edit', lambda d: d.metadata.update(test=True))
    elif mutation == 'video':
        Path(b.media_controller.path).write_bytes(b'changed')
    elif mutation == 'draft':
        b.addLine()
        b.stage('text', 'User typing')
    else:
        b._set_document(Document(), '')
    assert not b.hardsub.apply(False)
    assert not any(c.text == 'OCR text' for c in b.editor.document.cues)


def test_errors_cancel_and_document_switch_reject_queued_results(bridge):
    b = bridge
    assert b.hardsub.analyze({})
    complete(b, [row()], cancelled=True)
    assert not b.hardsub.rows and b.count == 0
    assert b.hardsub.analyze({})
    complete(b, error='OCR failed')
    assert b.hardsub.error and 'OCR failed' in b.hardsub.status
    assert b.hardsub.analyze({})
    old = b.hardsub._job
    b._set_document(Document(), '')
    old.signals.result.emit({'rows': [row()]})
    old.signals.finished.emit({'error': '', 'cancelled': False})
    assert not b.hardsub.rows and b.count == 0 and old.cancelled.is_set()


def test_immutable_online_original_is_protected(bridge):
    from types import SimpleNamespace
    b = bridge
    assert b.hardsub.analyze({})
    complete(b, [row()])
    b.online.repository = SimpleNamespace(snapshot={'metadata': {}})
    try:
        assert not b.hardsub.canAppend
        assert not b.hardsub.apply(False) and b.count == 0
    finally:
        b.online.repository = None


@pytest.mark.parametrize('options', [{'x': 90, 'width': 50}, {'y': float('nan')}, {'step': 0},
                                     {'language': 'unknown'}, {'start': 'bad'}, {'end': '00:00:20.000'}])
def test_invalid_analysis_options_do_not_launch(bridge, options):
    assert not bridge.hardsub.analyze(options)
    assert bridge.hardsub.error and not bridge.hardsub.busy


def test_review_text_time_validation_and_literal_ass(bridge):
    b = bridge
    assert b.hardsub.analyze({})
    complete(b, [row()])
    assert not b.hardsub.editRow(0, 'Fixed', 'bad', '00:00:02.000')
    assert b.hardsub.rows[0]['text'] == 'OCR text'
    assert b.hardsub.editRow(0, '{\\p1}\nFixed', '00:00:01.100', '00:00:02.200')
    assert b.hardsub.apply(False)
    cue = b.editor.document.cues[0]
    assert cue.start == 1100 and cue.end == 2200
    assert plain_drawing_safe(cue.text)


def plain_drawing_safe(text):
    return '{' not in text and r'\p1' not in text and r'\N' in text


@pytest.mark.skipif(sys.platform != 'darwin' or not importlib.util.find_spec('Vision') or
                    os.environ.get('SUBSTANCE_TEST_VISION') != '1',
                    reason='Opt-in native macOS OCR service test')
def test_native_vision_recognizes_burned_video_and_ignores_blank_frames(tmp_path):
    path = make_video(tmp_path)
    info = engine_info()
    assert info['engine'] == 'vision'
    options = {'step': 500, 'minimum': 300, 'region': [0, .7, 1, .3], 'language': 'en-US', 'confidence': 60}
    job = HardsubJob(str(path), 0, 4000, options, info)
    result = []
    job.signals.result.connect(result.append)
    job.execute()
    assert len(result[0]['rows']) == 2, result
    assert 'burned in subtitle' in result[0]['rows'][0]['text'].casefold()
    assert 'second subtitle' in result[0]['rows'][1]['text'].casefold()
    assert abs(result[0]['rows'][0]['start'] - 1000) <= 500
    assert abs(result[0]['rows'][1]['end'] - 3000) <= 500


@pytest.mark.skipif(sys.platform != 'darwin' or not importlib.util.find_spec('Vision') or
                    os.environ.get('SUBSTANCE_TEST_VISION') != '1',
                    reason='Opt-in native macOS OCR service test')
def test_native_vision_async_controller_import(tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path / 'data'))
    path = make_video(tmp_path)
    b = Backend()
    try:
        b.media_controller.path = str(path)
        monkeypatch.setattr(type(b.media_controller), 'hasVideo', property(lambda self: True))
        monkeypatch.setattr(type(b.media_controller), 'duration', property(lambda self: 4000))
        b.hardsub.refreshEngine()
        assert b.hardsub.analyze({'language': 'en-US', 'step': 500, 'y': 70, 'height': 30})
        loop = QEventLoop()
        b.hardsub._job.signals.finished.connect(loop.quit)
        QTimer.singleShot(30000, loop.quit)
        loop.exec()
        assert not b.hardsub.busy and b.hardsub.canApply, b.hardsub.status
        assert len(b.hardsub.rows) == 2, b.hardsub.status
        assert b.hardsub.apply(True), b.hardsub.status
        assert b.count == 2 and b.editor.document.cues[0].translation == ''
        b.undo()
        assert b.count == 0
    finally:
        b.shutdown()
