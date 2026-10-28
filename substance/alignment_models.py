"""Downloadable acoustic alignment models, separate from transcription models."""

from PySide6.QtCore import QObject, Property, QThreadPool, Signal, Slot
from PySide6.QtWidgets import QFileDialog

from .document import load_document
from .forced_alignment import MODELS, MODEL_BY_ID
from .transcription import ModelDownload


class AlignmentModels(QObject):
    changed = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend, self.directory = backend, backend.data_dir / 'alignment-models'
        self._job, self._status, self._progress = None, '', 0.

    @Property(bool, notify=changed)
    def busy(self):
        return self._job is not None

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property('QVariantList', notify=changed)
    def models(self):
        return [{'id': m.id, 'title': m.title, 'installed': (self.directory/m.filename).is_file() and
                 (self.directory/m.filename).stat().st_size == m.size} for m in MODELS]

    @Property(bool, notify=changed)
    def semanticInstalled(self):
        from .semantic_models import installed
        return installed(self.directory)

    @Property(int, constant=True)
    def semanticBytes(self):
        from .semantic_models import FILES
        return sum(f.size for f in FILES)

    @Slot()
    def downloadSemantic(self):
        from .semantic_models import SemanticDownload
        if self.busy or self.backend.tools.busy:
            return
        self._job = SemanticDownload(self.directory)
        self._job.signals.progress.connect(self._progressed)
        self._job.signals.finished.connect(self._finished)
        self._status, self._progress = 'Скачиваем многоязычную модель…', 0.
        self.changed.emit()
        QThreadPool.globalInstance().start(self._job)

    @Slot(str)
    def download(self, model_id):
        if self.busy or model_id not in MODEL_BY_ID:
            return
        self._job = ModelDownload(MODEL_BY_ID[model_id], self.directory)
        self._job.signals.progress.connect(self._progressed)
        self._job.signals.finished.connect(self._finished)
        self._status, self._progress = 'Скачиваем модель для выбранного языка…', 0.
        self.changed.emit()
        QThreadPool.globalInstance().start(self._job)

    def _progressed(self, value, message):
        self._progress, self._status = value, message
        self.changed.emit()

    def _finished(self, result):
        self._job = None
        self._status = result['error'] or ('Загрузка остановлена.' if result['cancelled'] else 'Модель готова. Выравнивание работает локально.')
        self.changed.emit()

    @Slot()
    def cancel(self):
        if self._job:
            self._job.cancel()

    @Slot()
    @Slot(str)
    def importScript(self, kind='forced'):
        b = self.backend
        if self.busy or b.tools.busy or b.busy or not b.flush() or not b.flushCard():
            return
        path, _ = QFileDialog.getOpenFileName(None, 'Добавить текст для тайминга', '', 'Сценарий, субтитры или проект (*.txt *.ass *.ssa *.srt *.vtt *.substance)')
        if not path:
            return
        try:
            doc = load_document(path)
            if not doc.cues:
                raise ValueError('В файле нет реплик.')
            start = b.count
            def add(target):
                target.source_lines.update(doc.source_lines)
                target.cues.extend(doc.cues)
            b.editor.transact('Добавление сценария для тайминга', add)
            b.selection = set(range(start, b.count))
            b._current, b._anchor = start, start
            b._refresh()
            b.tools.open('semantic' if kind == 'semantic' else 'forced')
            self._status = f'Добавлено реплик: {len(doc.cues)}. Выберите диапазон звучания сценария.'
        except (OSError, ValueError, TypeError) as exc:
            self._status = str(exc)
        self.changed.emit()

    def shutdown(self):
        self.cancel()
