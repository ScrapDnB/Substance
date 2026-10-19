"""Actual presentation timestamps, streamed from ffprobe and cached per video."""
from bisect import bisect_left, bisect_right
from pathlib import Path
import json
import math
import re
import subprocess

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot

from .document import atomic_write
from .media import ffprobe_executable, process_options
from .timing_processing import nearest_frame
from .tool_jobs import video_identity
from .transcription import SpeechJob


def validate_times(values):
    if not isinstance(values, list) or len(values) < 2 or len(values) > 5000000:
        raise ValueError('В индексе должно быть от двух до пяти миллионов кадров.')
    if any(type(v) is not int or v < 0 for v in values) or any(a >= b for a, b in zip(values, values[1:])):
        raise ValueError('Времена кадров должны возрастать.')
    return values


def step_position(times, position, direction, fps):
    if not times:
        return math.ceil(max(0, round(position * fps / 1000) + direction) * 1000 / fps)
    if direction > 0:
        at = bisect_right(times, position + 1)
    else:
        at = bisect_left(times, position - 1) - 1
    return times[max(0, min(len(times)-1, at))]


class FrameIndexJob(SpeechJob):
    def __init__(self, path, directory, duration):
        super().__init__()
        self.path, self.directory, self.duration = path, Path(directory), duration

    def execute(self):
        executable = ffprobe_executable()
        if not executable:
            raise ValueError('FFprobe отсутствует. Установите FFmpeg или обновите сборку Substance.')
        identity = video_identity(self.path)
        metadata = subprocess.run([executable, '-v', 'error', '-show_entries', 'format=start_time',
            '-of', 'json', self.path], capture_output=True, text=True, timeout=15, **process_options())
        if metadata.returncode:
            raise ValueError('Не удалось прочитать начало видео.')
        origin = float(json.loads(metadata.stdout).get('format', {}).get('start_time', 0)) * 1000
        self.check_cancelled()
        self.process = subprocess.Popen([executable, '-v', 'error', '-select_streams', 'v:0',
            '-show_frames', '-show_entries', 'frame=best_effort_timestamp_time', '-of', 'compact=p=0', self.path],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, **process_options())
        times = []
        for line in self.process.stdout:
            self.check_cancelled()
            match = re.search(r'best_effort_timestamp_time=(-?\d+(?:\.\d+)?)', line)
            if not match:
                continue
            when = float(match[1]) * 1000
            stamp = round(when - origin)
            if stamp < 0:
                continue
            if not times or stamp > times[-1]:
                times.append(stamp)
            if len(times) > 5000000:
                raise ValueError('Видео содержит больше пяти миллионов кадров.')
            if len(times) % 250 == 0:
                self.signals.progress.emit(min(.99, stamp/max(1, self.duration)), f'Проиндексировано кадров: {len(times)}')
        self.process.stdout.close()
        self.process.wait()
        self.check_cancelled()
        if self.process.returncode:
            raise ValueError('FFprobe не смог прочитать кадры этого видео.')
        validate_times(times)
        if video_identity(self.path) != identity:
            raise ValueError('Видео изменилось во время чтения кадров. Повторите анализ.')
        record = {'version': 1, 'identity': identity, 'times': times, 'origin': origin}
        self.directory.mkdir(parents=True, exist_ok=True)
        atomic_write(self.directory / (identity + '.json'), json.dumps(record).encode())
        self.signals.result.emit(record)


class FrameController(QObject):
    changed = Signal()
    requested = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend, self.times = backend, []
        self.directory = backend.data_dir / 'frame-index'
        self._job, self._received, self._key, self._path = None, None, None, ''
        self._status, self._progress = '', 0.
        backend.media_controller.changed.connect(self._sync)

    @Property(bool, notify=changed)
    def busy(self):
        return self._job is not None

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property(int, notify=changed)
    def count(self):
        return len(self.times)

    @Property(bool, notify=changed)
    def variableRate(self):
        return bool(self.times and max(b-a for a,b in zip(self.times, self.times[1:])) - min(b-a for a,b in zip(self.times, self.times[1:])) > 2)

    def _sync(self):
        media = self.backend.media_controller
        try:
            stat = Path(media.path).stat() if media.path else None
            key = (media.path, stat.st_size, stat.st_mtime_ns) if stat else None
            if key == self._key:
                return
            self.cancel()
            self._key, self._path, self.times = key, media.path, []
            self._status, self._progress = '', 0.
            if key:
                identity = video_identity(media.path)
                path = self.directory / (identity + '.json')
                if path.is_file():
                    record = json.loads(path.read_text())
                    if record.get('identity') == identity and record.get('version') == 1:
                        self.times = validate_times(record['times'])
                        self._status = f'Загружены временные метки {len(self.times)} кадров.'
        except (OSError, ValueError, KeyError, TypeError):
            self.times = []
        self.changed.emit()

    @Slot()
    def open(self):
        self._sync()
        self.requested.emit()

    @Slot()
    def build(self):
        media = self.backend.media_controller
        if self.busy:
            return
        if not media.hasVideo:
            self._status = 'Сначала откройте видео.'
            self.changed.emit()
            return
        self._path, self._received = media.path, None
        self._job = FrameIndexJob(media.path, self.directory, media.duration)
        self._job.signals.result.connect(self._receive)
        self._job.signals.progress.connect(self._progressed)
        self._job.signals.finished.connect(self._finished)
        self._progress, self._status = 0., 'Читаем реальные времена кадров…'
        self.changed.emit()
        QThreadPool.globalInstance().start(self._job)

    def _receive(self, record):
        self._received = record

    def _progressed(self, value, message):
        self._progress, self._status = value, message
        self.changed.emit()

    def _finished(self, result):
        self._job = None
        if result['error']:
            self._status = result['error']
        elif result['cancelled'] or self._path != self.backend.media_controller.path:
            self._status = 'Чтение кадров остановлено.'
        elif self._received:
            self.times = self._received['times']
            self._progress = 1.
            self._status = f'Готово: {len(self.times)} кадров. Покадровый переход и округление используют реальные метки.'
        self.changed.emit()

    @Slot()
    def cancel(self):
        if self._job:
            self._job.cancel()

    def nearest(self, value):
        return nearest_frame(value, self.times, self.backend.fps)

    def step(self, value, direction):
        return step_position(self.times, value, direction, self.backend.fps)

    def shutdown(self):
        self.cancel()
