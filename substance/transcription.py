"""Offline whisper.cpp jobs, verified model downloads, and timestamp parsing.

Only the worker touches audio or runs inference. Qt signals deliver immutable
segments to the controller; the document is changed on the GUI thread.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import urllib.request
import wave

import certifi
from PySide6.QtCore import QObject, QRunnable, Signal

from .media import ffmpeg_executable, process_options
from .speech_timing import PhraseAssembler, SpeechTimeline, SpeechTokens, TimingOptions, speech_word, wrap_subtitle

MODEL_REVISION = '5359861c739e955e79d9a303bcbc70fb988958b1'
VAD_FILENAME = 'ggml-silero-v6.2.0.bin'
VAD_REVISION = '9ffd54a1e1ee413ddf265af9913beaf518d1639b'
VAD_SIZE = 885098
VAD_SHA256 = '2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987'


@dataclass(frozen=True)
class SpeechModel:
    id: str
    title: str
    size: int
    sha256: str

    @property
    def filename(self):
        return f'ggml-{self.id}.bin'

    @property
    def url(self):
        return f'https://huggingface.co/ggerganov/whisper.cpp/resolve/{MODEL_REVISION}/{self.filename}'


MODELS = [
    SpeechModel('tiny', 'Tiny · быстрый черновик · 74 МиБ', 77691713, 'be07e048e1e599ad46341c8d2a135645097a538221678b7acdd1b1919c6e1b21'),
    SpeechModel('base', 'Base · лёгкая · 141 МиБ', 147951465, '60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe'),
    SpeechModel('small', 'Small · сбалансированная · 465 МиБ', 487601967, '1be3a9b2063867b937e64e2ec7483364a79917e157fa98c5d94b5c1fffea987b'),
    SpeechModel('medium', 'Medium · точная · 1,43 ГиБ', 1533763059, '6c14d5adee5f86394037b4e4e8b59f1673b6cee10e3cf0b11bbdbee79c156208'),
    SpeechModel('large-v3-turbo', 'Large v3 Turbo · 1,51 ГиБ', 1624555275, '1fc70f774d38eb169993ac391eea357ef47c88757ef72ee5943879b7e8e2bc69'),
]
MODEL_BY_ID = {model.id: model for model in MODELS}
LANGUAGES = [('auto', 'Определить автоматически'), ('ru', 'Русский'), ('en', 'Английский'),
             ('ja', 'Японский'), ('ko', 'Корейский'), ('zh', 'Китайский'), ('de', 'Немецкий'),
             ('fr', 'Французский'), ('es', 'Испанский'), ('it', 'Итальянский'), ('pt', 'Португальский'),
             ('uk', 'Украинский'), ('pl', 'Польский'), ('tr', 'Турецкий'), ('ar', 'Арабский'), ('hi', 'Хинди')]


def whisper_executable() -> str:
    name = 'whisper-cli.exe' if os.name == 'nt' else 'whisper-cli'
    root = Path(__file__).resolve().parents[1]
    candidates = [Path(getattr(sys, '_MEIPASS', root)) / 'whisper' / name, root / 'build/whisper' / name]
    override = os.environ.get('SUBSTANCE_WHISPER')
    if override:
        candidates.insert(0, Path(override))
    for path in candidates:
        if path.is_file():
            return str(path)
    found = shutil.which(name)
    return found or ''


def vad_model_path():
    root = Path(__file__).resolve().parents[1]
    for path in (Path(getattr(sys, '_MEIPASS', root)) / 'whisper' / VAD_FILENAME,
                 root / 'build/whisper' / VAD_FILENAME):
        if path.is_file():
            return path
    return None


class Cancelled(Exception):
    pass


class SpeechSignals(QObject):
    segment = Signal(object)
    result = Signal(object)
    progress = Signal(float, str)
    finished = Signal(object)


class SpeechJob(QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = SpeechSignals()
        self.cancelled = threading.Event()
        self.process = None

    def cancel(self):
        self.cancelled.set()
        process = self.process
        if process and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    def check_cancelled(self):
        if self.cancelled.is_set():
            raise Cancelled()

    def run(self):
        error = ''
        try:
            self.check_cancelled()
            self.execute()
        except Cancelled:
            pass
        except Exception as exc:
            if not self.cancelled.is_set():
                error = str(exc)
        finally:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            self.signals.finished.emit({'cancelled': self.cancelled.is_set(), 'error': error})


def verify_model(path, model, cancelled):
    if not path.is_file() or path.stat().st_size != model.size:
        raise ValueError('Модель отсутствует или повреждена. Скачайте её заново.')
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(1024 * 1024):
            if cancelled.is_set():
                raise Cancelled()
            digest.update(block)
    if digest.hexdigest() != model.sha256:
        raise ValueError('Контрольная сумма модели не совпадает. Удалите модель и скачайте заново.')


class ModelDownload(SpeechJob):
    def __init__(self, model, directory):
        super().__init__()
        self.model, self.directory = model, Path(directory)

    def execute(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(self.directory).free < self.model.size + 64 * 1024 * 1024:
            raise ValueError('Недостаточно свободного места для модели')
        target = self.directory / self.model.filename
        # Unique partial names also isolate downloads in different app windows.
        fd, partial_name = tempfile.mkstemp(prefix=self.model.filename + '.', suffix='.part', dir=self.directory)
        partial = Path(partial_name)
        try:
            digest, total = hashlib.sha256(), 0
            context = ssl.create_default_context(cafile=certifi.where())
            request = urllib.request.Request(self.model.url, headers={'User-Agent': 'Substance/local-speech'})
            with os.fdopen(fd, 'wb') as output, urllib.request.urlopen(request, context=context, timeout=15) as response:
                while True:
                    self.check_cancelled()
                    block = response.read(1024 * 1024)
                    if not block:
                        break
                    total += len(block)
                    if total > self.model.size:
                        raise ValueError('Сервер вернул неверный размер модели')
                    digest.update(block)
                    output.write(block)
                    self.signals.progress.emit(total / self.model.size, f'Скачивание: {total // 1048576} / {self.model.size // 1048576} МиБ')
                output.flush()
                os.fsync(output.fileno())
            self.check_cancelled()
            if total != self.model.size or digest.hexdigest() != self.model.sha256:
                raise ValueError('Загруженная модель не прошла проверку целостности. Повторите скачивание.')
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)


SEGMENT = re.compile(r'^\[(\d+:\d{2}:\d{2}[.,]\d{3})\s+-->\s+(\d+:\d{2}:\d{2}[.,]\d{3})\]\s*(.*)$')
PROGRESS = re.compile(r'whisper_print_progress_callback: progress =\s*(\d+)%')
VAD_INTERVAL = re.compile(r'vad_segment_info: orig_start: ([\d.]+), orig_end: ([\d.]+)')
VAD_MAPPING = re.compile(r'vad_segment_info: orig_start: ([\d.]+), orig_end: ([\d.]+), vad_start: ([\d.]+), vad_end: ([\d.]+)')


def timestamp_ms(value):
    hours, minutes, seconds, millis = re.split(r'[:.,]', value)
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def parse_segment(line, offset, end, width):
    match = SEGMENT.match(line.strip())
    if not match:
        return None
    start = offset + timestamp_ms(match[1])
    stop = min(end, offset + timestamp_ms(match[2]))
    text = wrap_subtitle(match[3], width)
    if start >= end or stop <= start or not text:
        return None
    return {'start': start, 'end': stop, 'text': text}


class TranscriptionJob(SpeechJob):
    def __init__(self, executable, model, model_path, media, track, language, start, end, width, cpu=False, timing=None):
        super().__init__()
        self.executable, self.model, self.model_path = executable, model, Path(model_path)
        self.media, self.track, self.language = media, track, language
        self.start, self.end, self.width, self.cpu = start, end, width, cpu
        self.timing = timing or TimingOptions()
        self.capture_words = False
        self.words = []

    def execute(self):
        self.signals.progress.emit(0, 'Проверка модели…')
        verify_model(self.model_path, self.model, self.cancelled)
        vad = vad_model_path()
        if not vad:
            raise ValueError('Модель выделения речи отсутствует. Обновите сборку приложения или выполните scripts/build_whisper.py.')
        verify_model(vad, SpeechModel('silero-v6.2.0', '', VAD_SIZE, VAD_SHA256), self.cancelled)
        with tempfile.TemporaryDirectory(prefix='substance-speech-') as directory:
            audio = Path(directory) / 'audio.wav'
            self.signals.progress.emit(0, 'Подготовка аудиодорожки…')
            command = [ffmpeg_executable(), '-nostdin', '-v', 'error', '-ss', str(self.start / 1000),
                       '-i', self.media, '-t', str((self.end - self.start) / 1000), '-map', f'0:a:{self.track}',
                       '-vn', '-ac', '1', '-ar', '16000', '-c:a', 'pcm_s16le', '-y', str(audio)]
            with tempfile.TemporaryFile() as errors:
                self.process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors, **process_options())
                while self.process.poll() is None:
                    if self.cancelled.wait(0.1):
                        raise Cancelled()
                self.check_cancelled()
                if self.process.returncode:
                    errors.seek(0)
                    raise ValueError('Не удалось подготовить аудио: ' + errors.read(3000).decode(errors='replace'))
            with wave.open(str(audio), 'rb') as stream:
                duration = round(stream.getnframes() * 1000 / stream.getframerate())
            if duration <= 0:
                raise ValueError('В выбранном диапазоне нет аудио')
            end = min(self.end, self.start + duration)
            # The bundled CLI streams lossless token bytes and acoustic DTW
            # boundaries. A stock CLI can supply the same data in final JSON.
            stamp = Path(self.executable).with_name('build.json')
            try:
                streaming = json.loads(stamp.read_text()).get('tokens_protocol') == 1
            except (OSError, ValueError):
                streaming = False
            output = Path(directory) / 'transcript'
            command = [self.executable, '-m', str(self.model_path), '-f', str(audio), '-l', self.language,
                       '-pp', '-sns', '-t', str(min(8, os.cpu_count() or 2)),
                       '-dtw', self.model.id.replace('-', '.'), '-nfa',
                       '--vad', '-vm', str(vad), '-vsd', '250', '-vp', '60']
            if streaming:
                command.append('--substance-tokens')
            else:
                command.extend(['-ojf', '-of', str(output)])
            if self.cpu:
                command.append('-ng')
            self.check_cancelled()
            self.signals.progress.emit(0, 'Распознавание…')
            self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                            text=True, encoding='utf-8', errors='surrogateescape', bufsize=1, **process_options())
            if self.cancelled.is_set():
                self.cancel()
            log = deque(maxlen=12)
            intervals = []
            timeline = SpeechTimeline(self.start)
            tokens = SpeechTokens()
            phrases = PhraseAssembler(self.width, self.timing, self.start, end)

            def emit_words(words):
                for item in words:
                    word = speech_word(item, intervals)
                    if word:
                        if self.capture_words:
                            self.words.append(word)
                        for phrase in phrases.feed(word):
                            self.signals.segment.emit(phrase)

            try:
                for line in self.process.stdout:
                    self.check_cancelled()
                    if match := VAD_MAPPING.search(line):
                        bounds = [round(float(value) * 1000) for value in match.groups()]
                        timeline.add(*bounds)
                        intervals.append((self.start + bounds[0], min(end, self.start + bounds[1])))
                    elif line.startswith('SUBSTANCE_TOKENS '):
                        segment = json.loads(line.removeprefix('SUBSTANCE_TOKENS '))
                        for token in timeline.tokens(segment):
                            emit_words(tokens.feed(token))
                        progress = segment['end'] / max(1, end - self.start)
                        self.signals.progress.emit(min(0.99, progress), 'Распознавание…')
                    elif match := PROGRESS.search(line):
                        self.signals.progress.emit(min(0.99, int(match[1]) / 100), 'Распознавание…')
                    elif line.strip():
                        log.append(line.strip())
                self.process.wait()
                self.check_cancelled()
                if not self.process.returncode:
                    if not streaming:
                        result = json.loads(output.with_suffix('.json').read_text(encoding='utf-8', errors='surrogateescape'))
                        for segment in result['transcription']:
                            # Whisper's vocabulary reserves IDs >= 50257 for
                            # non-text tokens. JSON stores byte fragments in
                            # otherwise normal strings; keep them losslessly.
                            rows = [{'hex': t['text'].encode('utf-8', errors='surrogateescape').hex(),
                                     'dtw': round(t['t_dtw'] * 10), 'end': t.get('offsets', {}).get('to', 0)}
                                    for t in segment['tokens'] if t['id'] < 50257]
                            for token in timeline.tokens({'tokens': rows, 'end': segment['offsets']['to']}):
                                emit_words(tokens.feed(token))
                    emit_words(tokens.finish())
            finally:
                self.process.stdout.close()
                for phrase in phrases.finish():
                    self.signals.segment.emit(phrase)
            self.check_cancelled()
            if self.process.returncode:
                raise ValueError('Ошибка whisper.cpp: ' + '\n'.join(log)[-2500:])
