"""Asynchronous playback, audio analysis and metadata probing."""
from __future__ import annotations

from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import sys

import numpy as np
from PySide6.QtCore import QObject, Property, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink


def ffmpeg_executable() -> str:
    if getattr(sys, 'frozen', False):
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    candidate = shutil.which("ffmpeg")
    if candidate:
        return candidate
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def ffprobe_executable() -> str | None:
    bundled = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
    override = os.environ.get("SUBSTANCE_FFPROBE")
    return override if override and Path(override).is_file() else str(bundled) if bundled.is_file() else shutil.which("ffprobe")


class AudioAnalysis(QObject):
    completed = Signal(object, object, object)
    progress = Signal(float)
    metadata = Signal(dict)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, path: str, duration: int, track=0):
        super().__init__()
        self.path, self.duration, self.track = path, duration, track
        self.cancelled = threading.Event()
        self.process = None

    def cancel(self):
        self.cancelled.set()
        if self.process is not None and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass

    def _probe(self):
        probe = ffprobe_executable()
        if not probe:
            return
        try:
            self.process = subprocess.Popen([probe, "-v", "error", "-show_streams", "-show_format", "-of", "json", self.path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **process_options())
            out, _ = self.process.communicate(timeout=15)
            if self.cancelled.is_set():
                return
            data = json.loads(out)
            video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
            num, den = video.get("avg_frame_rate", "0/1").split("/")
            fps = float(num) / float(den) if float(den) else 0
            self.duration = round(float(data.get("format", {}).get("duration", 0)) * 1000) or self.duration
            self.metadata.emit({"fps": fps, "duration": self.duration, "width": video.get("width", 0), "height": video.get("height", 0)})
        except (OSError, ValueError, ZeroDivisionError, subprocess.TimeoutExpired):
            if self.process and self.process.poll() is None:
                self.process.kill()

    @Slot()
    def run(self):
        try:
            self._probe()
            if self.cancelled.is_set():
                return
            fft_window = np.hanning(256).astype(np.float32)
            peaks = []
            spectrum = bytearray()
            residual = b""
            last_update = 0.0
            with tempfile.TemporaryFile() as error_log:
                self.process = subprocess.Popen([ffmpeg_executable(), "-nostdin", "-v", "error", "-i", self.path, "-map", f"0:a:{self.track}", "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "pipe:1"], stdout=subprocess.PIPE, stderr=error_log, **process_options())
                while not self.cancelled.is_set():
                    chunk = self.process.stdout.read(64000)
                    if not chunk:
                        break
                    chunk = residual + chunk
                    frames = len(chunk) // 640
                    residual = chunk[frames * 640:]
                    if not frames:
                        continue
                    pcm = np.frombuffer(chunk[:frames * 640], dtype="<f4").reshape(-1, 160)
                    peaks.extend(np.max(np.abs(pcm), axis=1).tolist())
                    padded = np.pad(pcm, ((0, 0), (0, 96))) * fft_window
                    power = np.abs(np.fft.rfft(padded, axis=1))[:, 1:129].reshape(-1, 64, 2).max(axis=2)
                    intensity = np.clip((20 * np.log10(power + 1e-7) + 65) * 255 / 65, 0, 255).astype(np.uint8)
                    spectrum.extend(intensity.tobytes())
                    now = time.monotonic()
                    if now - last_update > 0.2:
                        self.progress.emit(min(0.99, len(peaks) * 10 / max(1, self.duration)))
                        last_update = now
                if self.cancelled.is_set():
                    self.cancel()
                    self.process.wait(timeout=5)
                    return
                status = self.process.wait(timeout=10)
                if status:
                    error_log.seek(0)
                    raise ValueError(error_log.read(4000).decode(errors="replace").strip() or "В файле нет выбранной аудиодорожки")
            self.completed.emit(np.asarray(peaks, dtype=np.float32), np.frombuffer(bytes(spectrum), dtype=np.uint8).reshape(-1, 64), [])
        except Exception as exc:
            if not self.cancelled.is_set():
                self.failed.emit(str(exc))
        finally:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.finished.emit()


def process_options():
    return {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


class KeyframeAnalysis(QObject):
    completed = Signal(object)
    finished = Signal()

    def __init__(self, path):
        super().__init__()
        self.path = path
        self.process = None
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass

    @Slot()
    def run(self):
        try:
            probe = ffprobe_executable()
            if not probe or self.cancelled.is_set():
                return
            self.process = subprocess.Popen([probe, "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey", "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0", self.path], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, **process_options())
            if self.cancelled.is_set():
                return
            output, _ = self.process.communicate(timeout=120)
            times = []
            for line in output.decode(errors="replace").splitlines():
                try:
                    times.append(round(float(line.split(",")[0]) * 1000))
                except ValueError:
                    pass
            if not self.cancelled.is_set():
                self.completed.emit(times)
        except (OSError, subprocess.TimeoutExpired):
            self.cancel()
        finally:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.finished.emit()


class MediaController(QObject):
    changed = Signal()
    positionChanged = Signal()
    analysisChanged = Signal()
    metadataReady = Signal(dict)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.player.setActiveSubtitleTrack(-1)
        self.player.positionChanged.connect(self._position)
        self.player.durationChanged.connect(self.changed)
        self.player.playbackStateChanged.connect(self.changed)
        self.player.tracksChanged.connect(self.changed)
        self.player.mediaStatusChanged.connect(self._media_status)
        self.player.errorOccurred.connect(lambda code, message: self.error.emit(message))
        self.path = ""
        self.peaks = np.empty(0, dtype=np.float32)
        self.spectrum = np.empty((0, 64), dtype=np.uint8)
        self.keyframes: list[int] = []
        self._progress = 0.0
        self._busy = False
        self._workers = []
        self._stop_at = -1
        self._loop_start = -1
        self._loop = False
        self._generation = 0
        self._audio_generation = 0
        self._priming = False
        self._sink = None
        self._frame_position = 0
        self._video_width, self._video_height = 1920, 1080

    @Property(int, notify=positionChanged)
    def position(self):
        return self.player.position()

    @Property(int, notify=changed)
    def duration(self):
        return self.player.duration()

    @Property(bool, notify=changed)
    def playing(self):
        return self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    @Property(str, notify=changed)
    def name(self):
        return Path(self.path).name if self.path else "Медиа не подключено"

    @Property(bool, notify=changed)
    def hasMedia(self):
        return bool(self.path)

    @Property(float, notify=analysisChanged)
    def progress(self):
        return self._progress

    @Property(bool, notify=analysisChanged)
    def busy(self):
        return self._busy

    @Property(int, notify=analysisChanged)
    def keyframeCount(self):
        return len(self.keyframes)

    @Property(float, notify=changed)
    def volume(self):
        return self.output.volume()

    @Property(float, notify=changed)
    def rate(self):
        return self.player.playbackRate()

    @Property('QVariantList', notify=changed)
    def audioTracks(self):
        from PySide6.QtMultimedia import QMediaMetaData
        return [f"{i + 1} · {str(t.value(QMediaMetaData.Key.Title) or t.value(QMediaMetaData.Key.Language) or 'Аудиодорожка')}" for i, t in enumerate(self.player.audioTracks())]

    @Property(int, notify=changed)
    def activeAudio(self):
        return self.player.activeAudioTrack()

    @Property(int, notify=positionChanged)
    def framePosition(self):
        return self._frame_position if self.player.hasVideo() else self.position

    @Property(int, notify=changed)
    def videoWidth(self):
        return self._video_width

    @Property(int, notify=changed)
    def videoHeight(self):
        return self._video_height

    @Slot(QObject)
    def setVideoSink(self, sink):
        if isinstance(sink, QVideoSink):
            if self._sink is not None:
                try:
                    self._sink.videoFrameChanged.disconnect(self._first_frame)
                except (RuntimeError, TypeError):
                    pass
            self._sink = sink
            sink.videoFrameChanged.connect(self._first_frame)
            self.player.setVideoSink(sink)

    def _media_status(self, status):
        if status == QMediaPlayer.MediaStatus.LoadedMedia and self._priming:
            if self.player.hasVideo():
                self.player.play()
            else:
                self._priming = False

    def _first_frame(self, frame):
        if frame.isValid():
            self._frame_position = round(max(0, frame.startTime()) / 1000)
            size = frame.size()
            if (size.width(), size.height()) != (self._video_width, self._video_height):
                self._video_width, self._video_height = size.width(), size.height()
                self.changed.emit()
            self.positionChanged.emit()
        if self._priming and frame.isValid():
            self._priming = False
            self.player.pause()

    def _position(self, value):
        if self._stop_at >= 0 and value >= self._stop_at:
            if self._loop:
                self.player.setPosition(self._loop_start)
            else:
                self.player.pause()
                self._stop_at = -1
        self.positionChanged.emit()

    @Slot(int)
    def seek(self, value):
        self._stop_at = -1
        self.player.setPosition(max(0, value))

    @Slot()
    def toggle(self):
        self._stop_at = -1
        if self.playing:
            self.player.pause()
        else:
            self.player.play()

    @Slot(int, int, bool)
    def playRange(self, start, end, loop=False):
        self._loop_start, self._stop_at, self._loop = start, end, loop
        self.player.setPosition(start)
        self.player.play()

    @Slot(float)
    def setVolume(self, value):
        self.output.setVolume(max(0, min(1, value)))
        self.changed.emit()

    @Slot(float)
    def setRate(self, value):
        self.player.setPlaybackRate(max(0.25, min(2, value)))
        self.changed.emit()

    @Slot(int)
    def setAudioTrack(self, value):
        self.player.setActiveAudioTrack(value)
        self._analyze(value)
        self.changed.emit()

    def open(self, path):
        self.cancel_analysis()
        self._generation += 1
        self.player.stop()
        self.path = str(path)
        self.peaks = np.empty(0, dtype=np.float32)
        self.spectrum = np.empty((0, 64), dtype=np.uint8)
        self.keyframes = []
        self._frame_position = 0
        self._priming = True
        self.player.setSource(QUrl.fromLocalFile(self.path))
        self.player.setActiveSubtitleTrack(-1)
        self.changed.emit()
        self._analyze(0)
        if ffprobe_executable():
            worker = KeyframeAnalysis(self.path)
            worker.generation = self._generation
            self._start_worker(worker, lambda w: w.completed.connect(self._keyframes))

    def clear(self):
        self.cancel_analysis()
        self._generation += 1
        self._audio_generation += 1
        self.player.stop()
        self.player.setSource(QUrl())
        self.path = ""
        self.peaks = np.empty(0, dtype=np.float32)
        self.spectrum = np.empty((0, 64), dtype=np.uint8)
        self.keyframes = []
        self.changed.emit()
        self.analysisChanged.emit()

    def _start_worker(self, worker, connect):
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        pair = (thread, worker)
        self._workers.append(pair)
        def cleanup():
            if pair in self._workers:
                self._workers.remove(pair)
            thread.deleteLater()
        thread.finished.connect(cleanup)
        connect(worker)
        thread.start()

    def _analyze(self, track):
        # Cancel old audio workers, keep a running keyframe scan if the media is unchanged.
        for _, worker in self._workers:
            if isinstance(worker, AudioAnalysis):
                worker.cancel()
        self._busy, self._progress = True, 0.0
        self.analysisChanged.emit()
        worker = AudioAnalysis(self.path, self.duration, track)
        self._audio_generation += 1
        worker.generation = self._generation
        worker.audio_generation = self._audio_generation
        def connect(w):
            w.progress.connect(self._analysis_progress)
            w.metadata.connect(self._metadata_ready)
            w.completed.connect(self._audio_ready)
            w.failed.connect(self._analysis_error)
        self._start_worker(worker, connect)

    def _analysis_progress(self, value):
        if not self._valid_audio_sender():
            return
        self._progress = value
        self.analysisChanged.emit()

    def _audio_ready(self, peaks, spectrum, keyframes):
        if not self._valid_audio_sender():
            return
        self.peaks, self.spectrum = peaks, spectrum
        self._busy, self._progress = False, 1.0
        self.analysisChanged.emit()

    def _keyframes(self, values):
        sender = self.sender()
        if sender and sender.generation != self._generation:
            return
        self.keyframes = values
        self.analysisChanged.emit()

    def _analysis_error(self, message):
        if not self._valid_audio_sender():
            return
        self._busy = False
        self.analysisChanged.emit()
        self.error.emit(message)

    def _valid_audio_sender(self):
        sender = self.sender()
        return not sender or (sender.generation == self._generation and sender.audio_generation == self._audio_generation)

    def _metadata_ready(self, values):
        if self._valid_audio_sender():
            self.metadataReady.emit(values)

    def cancel_analysis(self):
        for _, worker in list(self._workers):
            worker.cancel()
        self._busy = False

    def shutdown(self):
        self.player.stop()
        self.cancel_analysis()
        for thread, _ in list(self._workers):
            thread.quit()
            thread.wait(7000)
