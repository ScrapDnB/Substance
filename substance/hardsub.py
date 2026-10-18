"""Local OCR of burned-in video text, with bounded frame sampling and review."""
from collections import Counter
import base64
import csv
from difflib import SequenceMatcher
import importlib.util
import io
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

import cv2
import numpy as np

from .media import ffmpeg_executable, process_options
from .tool_jobs import video_identity
from .transcription import SpeechJob


def tesseract_executable(override=''):
    candidates = [override, os.environ.get('SUBSTANCE_TESSERACT', ''), shutil.which('tesseract'),
                  '/opt/homebrew/bin/tesseract', '/usr/local/bin/tesseract']
    for root in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA'):
        if os.environ.get(root):
            candidates.append(str(Path(os.environ[root]) / 'Tesseract-OCR' / 'tesseract.exe'))
    return next((str(p) for p in candidates if p and Path(p).is_file() and os.access(p, os.X_OK)), '')


def engine_info(override=''):
    if not override and sys.platform == 'darwin' and importlib.util.find_spec('Vision'):
        import Vision
        request = Vision.VNRecognizeTextRequest.alloc().init()
        request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
        languages, error = request.supportedRecognitionLanguagesAndReturnError_(None)
        if error:
            raise ValueError(str(error))
        return {'engine': 'vision', 'title': 'Apple Vision · локально', 'executable': '',
                'languages': list(languages)}
    executable = tesseract_executable(override)
    if not executable:
        return {'engine': '', 'title': 'OCR не установлен', 'executable': '', 'languages': []}
    result = subprocess.run([executable, '--list-langs'], capture_output=True, timeout=8,
                            text=True, encoding='utf-8', errors='replace', **process_options())
    if result.returncode:
        raise ValueError(result.stderr.strip() or 'Не удалось получить языки Tesseract')
    languages = [line.strip() for line in result.stdout.splitlines()
                 if re.fullmatch(r'[\w/-]+', line.strip()) and line.strip() != 'osd']
    return {'engine': 'tesseract', 'title': 'Tesseract · локально', 'executable': executable,
            'languages': languages}


def normalize(text):
    return ' '.join(text.split()).casefold()


def ass_text(text):
    # OCR is literal text, never executable ASS override/drawing syntax.
    return text.replace('\\', '＼').replace('{', '｛').replace('}', '｝').replace('\n', r'\N')


def parse_tsv(value, confidence):
    lines, scores = {}, []
    for row in csv.DictReader(io.StringIO(value), delimiter='\t', quoting=csv.QUOTE_NONE):
        if row.get('level') != '5' or not row.get('text', '').strip():
            continue
        score = float(row['conf']) / 100
        if score < confidence:
            continue
        key = tuple(row[k] for k in ('block_num', 'par_num', 'line_num'))
        lines.setdefault(key, []).append(row['text'].strip())
        scores.append(score)
    return '\n'.join(' '.join(words) for words in lines.values()), sum(scores) / max(1, len(scores))


class TextRuns:
    """Blank samples close a run; OCR jitter votes within one continuous run."""
    def __init__(self, step, minimum):
        self.step, self.minimum = step, minimum
        self.rows, self.active = [], None

    def feed(self, stamp, end, text, confidence, preview=''):
        key = normalize(text)
        same = self.active and key and (key == self.active['key'] or
            (min(len(key), len(self.active['key'])) >= 12 and
             SequenceMatcher(None, key, self.active['key'], autojunk=False).ratio() >= .94))
        if not same:
            self.close()
        if not key:
            return
        if self.active is None:
            self.active = {'start': stamp, 'end': end, 'key': key, 'votes': Counter(),
                           'scores': [], 'preview': preview}
        self.active['end'] = end
        self.active['votes'][text] += 1
        self.active['scores'].append(confidence)

    def close(self):
        if self.active:
            a = self.active
            if a['end'] - a['start'] >= self.minimum:
                self.rows.append({'start': a['start'], 'end': a['end'],
                                  'text': a['votes'].most_common(1)[0][0],
                                  'confidence': sum(a['scores']) / len(a['scores']),
                                  'preview': a['preview'], 'checked': True})
            self.active = None


def image_url(frame):
    h, w = frame.shape[:2]
    if w > 800:
        frame = cv2.resize(frame, (800, max(1, round(h * 800 / w))))
    ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise ValueError('Не удалось подготовить кадр')
    return 'data:image/jpeg;base64,' + base64.b64encode(encoded).decode('ascii')


class HardsubJob(SpeechJob):
    def __init__(self, path, start, end, options, engine, *, preview=False):
        super().__init__()
        self.path, self.start, self.end = path, start, end
        self.options, self.engine, self.preview = options, engine, preview
        self.decoder = None

    def cancel(self):
        super().cancel()
        if self.decoder and self.decoder.poll() is None:
            try:
                self.decoder.terminate()
            except OSError:
                pass

    def recognize(self, frame):
        self.check_cancelled()
        language = self.options['language']
        confidence = self.options['confidence'] / 100
        if self.engine['engine'] == 'vision':
            import objc
            import Vision
            from Foundation import NSData, NSDictionary, NSArray
            # A pool per frame keeps long videos from accumulating Cocoa objects.
            with objc.autorelease_pool():
                encoded = cv2.imencode('.png', frame)[1].tobytes()
                data = NSData.dataWithBytes_length_(encoded, len(encoded))
                request = Vision.VNRecognizeTextRequest.alloc().init()
                request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
                request.setRecognitionLanguages_(NSArray.arrayWithObject_(language))
                request.setUsesLanguageCorrection_(True)
                handler = Vision.VNImageRequestHandler.alloc().initWithData_options_(data, NSDictionary.dictionary())
                ok, error = handler.performRequests_error_(NSArray.arrayWithObject_(request), None)
                if not ok:
                    raise ValueError('Apple Vision: ' + (str(error) if error else
                        'системная служба распознавания недоступна. Проверьте доступ к службам macOS или выберите Tesseract.'))
                items = []
                for observation in request.results() or []:
                    candidates = observation.topCandidates_(1)
                    if candidates and candidates[0].confidence() >= confidence:
                        box = observation.boundingBox()
                        items.append((float(box.origin.y), float(box.origin.x),
                                      str(candidates[0].string()), float(candidates[0].confidence())))
                items.sort(key=lambda item: (-round(item[0], 2), item[1]))
                return '\n'.join(i[2] for i in items), sum(i[3] for i in items) / max(1, len(items))
        encoded = cv2.imencode('.png', frame)[1].tobytes()
        self.process = subprocess.Popen([self.engine['executable'], 'stdin', 'stdout', '-l', language,
                                         '--psm', '6', 'tsv'], stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, **process_options())
        if self.cancelled.is_set():
            self.cancel()
        try:
            out, error = self.process.communicate(encoded, timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.communicate()
            raise ValueError('Tesseract не ответил за 30 секунд')
        self.check_cancelled()
        if self.process.returncode:
            raise ValueError('Tesseract: ' + error.decode('utf-8', errors='replace')[-1500:])
        return parse_tsv(out.decode('utf-8', errors='replace'), confidence)

    def execute(self):
        self.check_cancelled()
        identity = video_identity(self.path)
        step = self.options.get('step', 250)
        tracker = TextRuns(step, self.options.get('minimum', 300))
        command = [ffmpeg_executable(), '-nostdin', '-v', 'error', '-ss', str(self.start / 1000),
                   '-i', self.path, '-t', str((self.end - self.start) / 1000), '-map', '0:v:0',
                   '-an', '-sn', '-vf', f'fps=1000/{step}:start_time=0,scale=1280:-2',
                   '-c:v', 'ppm', '-f', 'image2pipe']
        if self.preview:
            command.extend(['-frames:v', '1'])
        command.append('pipe:1')
        with tempfile.TemporaryFile() as errors:
            self.decoder = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors, **process_options())
            decoded = 0
            try:
                if self.cancelled.is_set():
                    self.cancel()
                stream = self.decoder.stdout
                while True:
                    self.check_cancelled()
                    magic = stream.readline()
                    if not magic:
                        break
                    if magic.strip() != b'P6':
                        raise ValueError('Не удалось прочитать кадр FFmpeg')
                    width, height = map(int, stream.readline().split())
                    if not (0 < width <= 1280 and 0 < height <= 16384) or stream.readline().strip() != b'255':
                        raise ValueError('Некорректный размер кадра')
                    pixels = stream.read(width * height * 3)
                    if len(pixels) != width * height * 3:
                        self.check_cancelled()
                        raise ValueError('Видео оборвалось при чтении кадра')
                    frame = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 3)[:, :, ::-1].copy()
                    stamp = self.start + decoded * step
                    decoded += 1
                    if self.preview:
                        self.signals.result.emit({'preview': image_url(frame), 'identity': identity})
                        break
                    x, y, w, h = self.options['region']
                    crop = frame[round(y * height):round((y + h) * height),
                                 round(x * width):round((x + w) * width)]
                    if not crop.size:
                        raise ValueError('Область распознавания слишком мала')
                    text, confidence = self.recognize(crop)
                    tracker.feed(stamp, min(self.end, stamp + step), text, confidence,
                                 image_url(crop) if text and (tracker.active is None or normalize(text) != tracker.active['key']) else '')
                    self.signals.progress.emit(min(.99, (stamp + step - self.start) / (self.end - self.start)),
                        f'Проверено кадров: {decoded}. Найдено фрагментов: {len(tracker.rows)}')
                self.decoder.wait(timeout=15)
                self.check_cancelled()
                if self.decoder.returncode:
                    errors.seek(0)
                    raise ValueError('FFmpeg: ' + errors.read().decode('utf-8', errors='replace')[-1500:])
                if not decoded:
                    raise ValueError('Нет кадров в выбранном диапазоне')
                if video_identity(self.path) != identity:
                    raise ValueError('Видео изменилось во время анализа. Повторите поиск.')
                if not self.preview:
                    tracker.close()
                    self.signals.result.emit({'identity': identity, 'rows': tracker.rows, 'frames': decoded})
            finally:
                if self.decoder.poll() is None:
                    self.decoder.kill()
                    self.decoder.wait()
                self.decoder.stdout.close()
