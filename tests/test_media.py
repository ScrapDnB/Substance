import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from pathlib import Path
import subprocess
import numpy as np
import pytest
from PySide6.QtGui import QImage, QPainter
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtMultimedia import QVideoSink
from PySide6.QtWidgets import QApplication

from substance.media import AudioAnalysis, KeyframeAnalysis, MediaController, ffmpeg_executable, ffprobe_executable, process_options
from substance.tasks import ExtractTask, SpellingTask
from substance.document import DEFAULT_ASS
from substance.visuals import AssRenderer, libass_path


def wait(milliseconds):
    # Release the Python GIL while native media callbacks deliver frames.
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp('media')
    subs = folder / 'embedded.ass'
    subs.write_text(DEFAULT_ASS + 'Dialogue: 0,0:00:00.20,0:00:01.50,Default,Mika,0,0,0,,Hello!\n', encoding="utf-8")
    clip = folder / 'test.mkv'
    subprocess.run([ffmpeg_executable(), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x180:rate=24:duration=2', '-f', 'lavfi', '-i', 'sine=frequency=420:duration=2', '-i', str(subs), '-map', '0:v', '-map', '1:a', '-map', '2:s', '-c:v', 'libx264', '-g', '24', '-c:a', 'pcm_s16le', '-c:s', 'ass', '-y', str(clip)], check=True, timeout=30, **process_options())
    return clip


def test_audio_spectrum_metadata_and_keyframes(app, media):
    results, errors, metadata = [], [], []
    analysis = AudioAnalysis(str(media), 2000)
    analysis.completed.connect(lambda peaks, spectrum, frames: results.append((peaks, spectrum)))
    analysis.metadata.connect(metadata.append)
    analysis.failed.connect(errors.append)
    analysis.run()
    assert not errors
    peaks, spectrum = results[0]
    assert 7900 <= len(peaks) <= 8100
    assert np.max(peaks) > 0.05
    assert 190 <= len(spectrum) <= 210
    assert spectrum.shape[1] == 64
    assert np.max(spectrum) > 0
    if ffprobe_executable():
        assert metadata[0]['fps'] == 24
        assert metadata[0]['width'] == 320
        keyframes = []
        analysis = KeyframeAnalysis(str(media))
        analysis.completed.connect(keyframes.extend)
        analysis.run()
        assert keyframes[:2] == [0, 1000]


def test_waveform_resolves_submillisecond_peaks_and_keeps_final_samples(app, tmp_path):
    import wave

    # Two transients inside the old 10 ms bin and a partial final analysis frame.
    samples = np.zeros(16013, dtype='<i2')
    samples[[8000, 8016, 16012]] = [16384, -24576, 28672]
    path = tmp_path / 'transients.wav'
    with wave.open(str(path), 'wb') as audio:
        audio.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
        audio.writeframes(samples.tobytes())
    results, errors, progress = [], [], []
    analysis = AudioAnalysis(str(path), 1001)
    analysis.completed.connect(lambda peaks, spectrum, frames: results.append((peaks, spectrum)))
    analysis.failed.connect(errors.append)
    analysis.progress.connect(progress.append)
    analysis.run()
    assert not errors
    peaks, spectrum = results[0]
    assert peaks.dtype == np.float32
    assert len(peaks) == 4004
    assert spectrum.shape == (101, 64)
    assert peaks[2000] == pytest.approx(0.5)
    assert np.all(peaks[2001:2004] == 0)
    assert peaks[2004] == pytest.approx(0.75)
    assert peaks[-1] == pytest.approx(0.875)
    assert progress and 0.98 <= progress[-1] <= 0.99


def test_embedded_subtitle_extraction_and_cancellation(app, media):
    results, errors = [], []
    task = ExtractTask(str(media), 0)
    task.signals.completed.connect(results.append)
    task.signals.failed.connect(errors.append)
    task.run()
    assert not errors
    cue = results[0].cues[0]
    assert (cue.start, cue.end, cue.original, cue.character) == (200, 1500, 'Hello!', 'Mika')
    assert results[0].media['path'] == str(media)
    cancelled = ExtractTask(str(media), 0)
    cancelled.cancel()
    cancelled.run()
    assert cancelled.process is None


def test_local_spelling_ignores_ass_tags_and_names(app):
    results, errors = [], []
    task = SpellingTask([(0, r'{\i1}helllo{\i0} Substance Mika')], 'en', ['Substance', 'Mika'])
    task.signals.completed.connect(results.append)
    task.signals.failed.connect(errors.append)
    task.run()
    assert not errors
    assert [r['word'] for r in results[0]] == ['helllo']
    assert 'hello' in results[0][0]['suggestions']


def test_exact_ass_overlay_is_visible_only_during_interval(app):
    if not libass_path():
        pytest.skip('Install libass for exact ASS preview')
    renderer = AssRenderer()
    try:
        renderer.set_script(DEFAULT_ASS + 'Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,Hello world\n')
        def render(timestamp):
            image = QImage(640, 360, QImage.Format.Format_RGBA8888)
            image.fill(0)
            painter = QPainter(image)
            renderer.render(painter, 640, 360, timestamp, 640, 360)
            painter.end()
            return np.frombuffer(image.constBits(), dtype=np.uint8).reshape(360, 640, 4)[:, :, 3].sum()
        assert render(2000) > 0
        assert render(0) == 0
        assert render(3000) == 0
    finally:
        renderer.close()


def test_native_media_primes_a_paused_video_frame(app, media):
    controller = MediaController()
    # Frame seeking does not require a physical audio device on CI runners.
    controller.player.setAudioOutput(None)
    sink = QVideoSink(controller)
    controller.setVideoSink(sink)
    try:
        controller.open(str(media))
        for _ in range(100):
            app.processEvents()
            if sink.videoFrame().isValid() and controller.videoWidth == 320:
                break
            wait(50)
        assert sink.videoFrame().isValid()
        assert controller.videoWidth == 320
        wait(100)
        assert not controller.playing
        captures = []
        controller.captured.connect(lambda image, timestamp, path: captures.append((image, timestamp, path)))
        controller.seek(1000)
        controller.captureFrame()
        for _ in range(100):
            if 900 <= controller.framePosition <= 1100 and captures:
                break
            wait(50)
        assert 900 <= controller.framePosition <= 1100
        assert len(captures) == 1
        image, timestamp, path = captures[0]
        assert (image.width(), image.height()) == (320, 180)
        assert 900 <= timestamp <= 1100
        assert path == str(media)
        assert not controller.playing
    finally:
        controller.shutdown()


def test_silent_video_has_empty_audio_without_error(app, tmp_path):
    path = tmp_path / 'silent.mp4'
    subprocess.run([ffmpeg_executable(), '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=160x90:rate=24:duration=0.2', '-c:v', 'libx264', '-y', str(path)], check=True, timeout=30, **process_options())
    results, errors = [], []
    worker = AudioAnalysis(str(path), 200)
    worker.completed.connect(lambda peaks, spectrum, frames: results.append((peaks, spectrum)))
    worker.failed.connect(errors.append)
    worker.run()
    assert not errors
    assert results[0][0].size == 0
    assert results[0][1].shape == (0, 64)
