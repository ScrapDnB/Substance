"""Decode PGS/VobSub images and retain their original display intervals."""
from copy import deepcopy
from pathlib import Path
import base64
import hashlib
import json
import subprocess
import sys
import tempfile

import cv2
import numpy as np
from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .media import ffprobe_executable, process_options
from .document import Cue
from .hardsub import HardsubJob, ass_text, image_url
from .timecode import format_time, parse_time
from .tool_jobs import video_identity

BITMAP_CODECS = {'hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub'}




def bitmap_identity(path):
    identities = [video_identity(path)]
    if Path(path).suffix.lower() == '.idx':
        identities.append(video_identity(Path(path).with_suffix('.sub')))
    return hashlib.sha256(':'.join(identities).encode()).hexdigest()


class BitmapJob(HardsubJob):
    def __init__(self, path, track, options, engine):
        super().__init__(path, 0, 0, options, engine)
        self.track = track

    def run(self):
        try:
            super().run()
        finally:
            if self.decoder and self.decoder.poll() is None:
                self.decoder.kill()
                self.decoder.wait()

    def execute(self):
        identity = bitmap_identity(self.path)
        rows = []
        command = ([sys.executable, '--decode-bitmaps'] if getattr(sys, 'frozen', False) else
                   [sys.executable, str(Path(__file__).with_name('bitmap_decode.py'))])
        with tempfile.TemporaryFile() as errors:
            self.decoder = subprocess.Popen(command + [self.path, str(self.track)], stdout=subprocess.PIPE,
                                            stderr=errors, text=True, encoding='utf-8', **process_options())
            for line in self.decoder.stdout:
                self.check_cancelled()
                item = json.loads(line)
                image = cv2.imdecode(np.frombuffer(base64.b64decode(item.pop('image')), dtype=np.uint8), cv2.IMREAD_COLOR)
                if image is None:
                    raise ValueError('Не удалось прочитать изображение субтитров.')
                text, confidence = self.recognize(image)
                rows.append(dict(item, text=text, confidence=confidence, preview=image_url(image),
                                 checked=bool(text) and item['end'] > item['start']))
                self.signals.progress.emit(0, f'Распознано изображений: {len(rows)}')
                if len(rows) >= 30000:
                    raise ValueError('В дорожке больше 30 000 изображений. Разделите материал.')
            self.decoder.stdout.close()
            self.decoder.wait()
            self.check_cancelled()
            if self.decoder.returncode:
                errors.seek(0)
                raise ValueError(errors.read().decode('utf-8', errors='replace')[-1500:])
        if bitmap_identity(self.path) != identity:
            raise ValueError('Исходный файл изменился. Повторите распознавание.')
        self.signals.result.emit({'rows': rows, 'identity': identity})


class BitmapController(QObject):
    changed = Signal()
    requested = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self._path, self._status = '', ''
        self._tracks, self._rows = [], []
        self._job, self._result, self._snapshot, self._editor = None, None, None, None
        self._progress, self._index, self._applied = 0., 0, False
        backend.changed.connect(self.changed)
        backend.documentReplaced.connect(self._replaced)

    @Property(bool, notify=changed)
    def busy(self):
        return self._job is not None

    @Property(str, notify=changed)
    def source(self):
        return self._path

    @Property(str, notify=changed)
    def status(self):
        return 'Документ изменился после анализа. Повторите распознавание.' if self.stale else self._status

    @Property(bool, notify=changed)
    def stale(self):
        return self._snapshot is not None and (self._editor is not self.backend.editor or self._snapshot != self.backend.editor.document or bool(self.backend.draft))

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property('QVariantList', notify=changed)
    def tracks(self):
        return [r['title'] for r in self._tracks]

    @Property('QVariantList', notify=changed)
    def rows(self):
        return [dict(r, number=i+1, time=format_time(r['start'])+' → '+format_time(r['end'])) for i,r in enumerate(self._rows)]

    @Property('QVariantMap', notify=changed)
    def preview(self):
        return dict(self._rows[self._index], index=self._index, startText=format_time(self._rows[self._index]['start']),
                    endText=format_time(self._rows[self._index]['end'])) if 0 <= self._index < len(self._rows) else {}

    @Property(bool, notify=changed)
    def canApply(self):
        return not self.busy and not self.stale and not self._applied and not self.backend.busy and any(r['checked'] and r['text'].strip() and r['end'] > r['start'] for r in self._rows)

    @Slot()
    def open(self):
        if self.backend.flush() and self.backend.flushCard():
            self.backend.hardsub.refreshEngine()
            self.requested.emit()

    @Slot()
    def chooseSource(self):
        path, _ = QFileDialog.getOpenFileName(None, 'Графические субтитры или видео с такой дорожкой', '', 'PGS, VobSub и Matroska (*.sup *.idx *.sub *.mkv *.mks)')
        if path:
            self.loadSource(path)

    @Slot(str, result=bool)
    def loadSource(self, path):
        if self.busy:
            return False
        try:
            path = Path(path)
            if path.suffix.lower() == '.sub':
                path = path.with_suffix('.idx')
            executable = ffprobe_executable()
            if not executable:
                raise ValueError('FFprobe отсутствует. Установите FFmpeg или обновите сборку.')
            info = subprocess.run([executable, '-v', 'error', '-show_entries', 'stream=index,codec_name,codec_type:stream_tags',
                '-of', 'json', str(path)], capture_output=True, text=True, encoding='utf-8', timeout=15, **process_options())
            if info.returncode:
                raise ValueError(info.stderr[-1500:] or 'Не удалось прочитать файл.')
            streams = json.loads(info.stdout).get('streams', [])
            self._tracks = [{'index': stream['index'], 'title': str(stream['index']+1) + ' · ' +
                stream.get('tags', {}).get('language', '') + ' · ' + stream['codec_name']}
                for stream in streams if stream.get('codec_name') in BITMAP_CODECS]
            if not self._tracks:
                raise ValueError('В файле нет графических дорожек PGS/VobSub.')
            self._path, self._rows, self._snapshot = str(path), [], None
            self._status = 'Выберите дорожку и язык текста, затем запустите распознавание.'
            self.changed.emit()
            return True
        except Exception as exc:
            self._status = str(exc)
            self.changed.emit()
            return False

    @Slot(int, str)
    def analyze(self, track, language):
        b = self.backend
        if self.busy or b.busy or not b.flush() or not b.flushCard():
            return
        if not 0 <= track < len(self._tracks) or language not in b.hardsub.languages or not b.hardsub.engineReady:
            self._status = 'Выберите файл, графическую дорожку и установленный язык OCR.'
            self.changed.emit()
            return
        self._snapshot, self._editor = deepcopy(b.editor.document), b.editor
        self._rows, self._applied, self._result = [], False, None
        self._job = BitmapJob(self._path, self._tracks[track]['index'], {'language': language, 'confidence': 0}, dict(b.hardsub._info))
        self._job.signals.result.connect(self._receive)
        self._job.signals.progress.connect(self._progressed)
        self._job.signals.finished.connect(self._finished)
        self._progress, self._status = 0., 'Читаем изображения субтитров…'
        self.changed.emit()
        QThreadPool.globalInstance().start(self._job)

    def _receive(self, result):
        self._result = result

    def _progressed(self, value, message):
        self._progress, self._status = value, message
        self.changed.emit()

    def _finished(self, result):
        self._job = None
        if result['error']:
            self._status = result['error']
        elif result['cancelled']:
            self._status = 'Распознавание остановлено. Документ не изменён.'
        elif self._result and not self.stale:
            self._rows, self._index, self._progress = self._result['rows'], 0, 1.
            self._status = f'Изображений: {len(self._rows)}. Проверьте текст по картинкам. Реплики без текста или времени окончания нужно исправить вручную.'
        self.changed.emit()

    @Slot(int)
    def previewRow(self, index):
        if not self.busy and 0 <= index < len(self._rows):
            self._index = index
            self.changed.emit()

    @Slot(int, bool)
    def check(self, index, checked):
        if not self.busy and 0 <= index < len(self._rows):
            self._rows[index]['checked'] = checked
            self.changed.emit()

    @Slot(bool)
    def checkAll(self, checked):
        if not self.busy:
            for row in self._rows:
                row['checked'] = checked and bool(row['text'].strip()) and row['end'] > row['start']
            self.changed.emit()

    @Slot(int, str, str, str, result=bool)
    def updateRow(self, index, text, start, end):
        if self.busy or not 0 <= index < len(self._rows):
            return False
        try:
            a, b = parse_time(start), parse_time(end)
            if b <= a or not text.strip():
                raise ValueError('Введите текст и время окончания после начала.')
            self._rows[index].update(text=text, start=a, end=b, checked=True)
            self._status = 'Исправление сохранено в предпросмотре.'
            self.changed.emit()
            return True
        except ValueError as exc:
            self._status = str(exc)
        self.changed.emit()
        return False

    @Slot(bool, result=bool)
    def apply(self, translation):
        b = self.backend
        if not b.flush() or not b.flushCard() or not self.canApply:
            return False
        try:
            if bitmap_identity(self._path) != self._result['identity']:
                raise ValueError('Исходный файл изменился. Повторите распознавание.')
            selected = [r for r in self._rows if r['checked']]
            if any(not r['text'].strip() or r['end'] <= r['start'] for r in selected):
                raise ValueError('Исправьте текст и интервалы всех отмеченных реплик.')
            def edit(doc):
                for r in selected:
                    text = ass_text(r['text'])
                    cue = Cue(start=r['start'], end=r['end'], text=text, original=text, translation='' if translation else None,
                              extras={'bitmap_source': {'file': Path(self._path).name, 'identity': self._result['identity']}})
                    doc.register_source(cue)
                    doc.cues.append(cue)
            b.editor.transact('Импорт графических субтитров', edit)
            self._snapshot, self._applied = None, True
            if b._current < 0 and b.count:
                b._current = b._anchor = 0
                b.selection = {0}
            b._refresh()
            self._status = f'Добавлено реплик: {len(selected)}. Доступна общая отмена.'
            self.changed.emit()
            return True
        except (OSError, ValueError, TypeError) as exc:
            self._status = str(exc)
            self.changed.emit()
            return False

    @Slot()
    def cancel(self):
        if self._job:
            self._job.cancel()

    def _replaced(self):
        self.cancel()
        self._snapshot, self._rows = None, []
        self.changed.emit()

    def shutdown(self):
        self.cancel()
