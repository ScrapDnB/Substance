"""Cancellable local analysis workers; results are proposals, never live edits."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from .document import atomic_write
from .editor_tools import align_words
from .media import ffmpeg_executable, process_options
from .transcription import SpeechJob, TranscriptionJob


def video_identity(path):
    path = Path(path)
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(str((stat.st_size, stat.st_mtime_ns)).encode())
    with path.open('rb') as stream:
        digest.update(stream.read(65536))
        stream.seek(max(0, stat.st_size - 65536))
        digest.update(stream.read(65536))
    return digest.hexdigest()


class SceneJob(SpeechJob):
    def __init__(self, path, threshold, duration, cache):
        super().__init__()
        self.path, self.threshold, self.duration, self.cache = path, threshold, duration, Path(cache)

    def execute(self):
        identity = video_identity(self.path)
        key = hashlib.sha256(f'scdet-v1:{identity}:{self.threshold}'.encode()).hexdigest()
        target = self.cache / (key + '.json')
        if target.is_file():
            try:
                result = json.loads(target.read_text('utf-8'))
                if result.get('identity') == identity and isinstance(result.get('times'), list):
                    self.signals.result.emit(result)
                    return
            except (OSError, ValueError, TypeError):
                pass
        self.signals.progress.emit(0, 'Поиск смен планов…')
        times = []
        command = [ffmpeg_executable(), '-nostdin', '-hide_banner', '-v', 'info', '-i', self.path,
                   '-map', '0:v:0', '-an', '-sn', '-vf',
                   f'scale=320:-2,scdet=t={self.threshold},metadata=mode=print:key=lavfi.scd.time',
                   '-f', 'null', '-']
        self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                                        text=True, encoding='utf-8', errors='replace', **process_options())
        if self.cancelled.is_set():
            self.cancel()
        errors = []
        try:
            for line in self.process.stderr:
                self.check_cancelled()
                if 'lavfi.scd.time=' in line:
                    value = line.split('lavfi.scd.time=', 1)[1].strip()
                    if re.fullmatch(r'\d+(?:\.\d+)?', value):
                        when = round(float(value) * 1000)
                        times.append(when)
                        self.signals.progress.emit(min(.99, when / max(1, self.duration)), f'Найдено склеек: {len(times)}')
                errors.append(line)
                errors = errors[-12:]
            self.process.wait()
        finally:
            self.process.stderr.close()
        self.check_cancelled()
        if self.process.returncode:
            raise ValueError('Не удалось найти смены планов: ' + ''.join(errors)[-1600:])
        if video_identity(self.path) != identity:
            raise ValueError('Видео изменилось во время анализа')
        result = {'identity': identity, 'threshold': self.threshold, 'times': sorted(set(times))}
        self.cache.mkdir(parents=True, exist_ok=True)
        atomic_write(target, json.dumps(result).encode())
        self.signals.result.emit(result)


class AlignmentJob(TranscriptionJob):
    def __init__(self, *args, document, indices, options, **kwargs):
        super().__init__(*args, **kwargs)
        self.document, self.indices, self.options = document, indices, options
        self.capture_words = True

    def execute(self):
        super().execute()
        self.check_cancelled()
        self.signals.progress.emit(.99, 'Сопоставление готового текста с речью…')
        result = align_words(self.document, self.indices, self.words,
                             max_shift=int(self.options.get('maxShift', 1000)),
                             lead=int(self.options.get('lead', 0)), tail=int(self.options.get('tail', 120)),
                             edges=self.options.get('edges', 'both'), cps=int(self.options.get('cps', 17)))
        self.check_cancelled()
        self.signals.result.emit(result)
