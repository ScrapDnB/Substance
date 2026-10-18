"""Review, stale-result guards, local undo and revision-protected online sends."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, QObject, Property, QSortFilterProxyModel, QThreadPool, QTimer, Qt, Signal, Slot
from PySide6.QtGui import QImage

from .images import crop_image, decode_image
from .document import identity
from .project import CharacterCard
from .portrait_analysis import ANALYSIS_PROFILES, candidate_key, combine_named_rows, unique_candidates
from .portrait_job import PortraitJob, PreparePortraitsJob
from .portrait_models import MODELS, shared_model_directory
from .timecode import format_time


class PortraitResultsModel(QAbstractListModel):
    """Stable delegate identities: selecting a face never resets the list."""
    PORTRAIT = Qt.ItemDataRole.UserRole + 1

    def __init__(self, controller):
        super().__init__(controller)
        self.controller = controller
        self._items = []
        self._generation = -1

    def roleNames(self):
        return {self.PORTRAIT: b'portrait'}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if index.isValid() and 0 <= index.row() < len(self._items) and role == self.PORTRAIT:
            return self._items[index.row()]
        return None

    @Slot()
    def sync(self):
        items = self.controller.rows
        if self._generation != self.controller._generation or len(items) != len(self._items):
            self.beginResetModel()
            self._generation = self.controller._generation
            self._items = items
            self.endResetModel()
        else:
            for row, item in enumerate(items):
                if item != self._items[row]:
                    self._items[row] = item
                    index = self.index(row)
                    self.dataChanged.emit(index, index, [self.PORTRAIT])


class PortraitResultsFilter(QSortFilterProxyModel):
    PORTRAIT = PortraitResultsModel.PORTRAIT

    def __init__(self, controller, source):
        super().__init__(controller)
        self.controller = controller
        self.setSourceModel(source)

    def filterAcceptsRow(self, source_row, parent):
        source = self.sourceModel()
        item = source.data(source.index(source_row, 0, parent), self.PORTRAIT)
        return bool(item and not item['merged'] and (item['cardId'] or self.controller.showUnnamed))


class PortraitsController(QObject):
    changed = Signal()
    charactersChanged = Signal()
    requested = Signal()
    showUnnamedChanged = Signal()
    selectionRequested = Signal(int)

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self._job = None
        self._generation = 0
        self._rows = []
        self._new_characters = {}
        self._snapshot = None
        self._context = None
        self._progress = 0.
        self._status = ''
        self._activity = ''
        self._show_unnamed = False
        self._save_visible = False
        self._save_status = ''
        self._save_progress = 0.
        self._save_total = self._save_done = 0
        self._prepared_records = {}
        self._mode = backend.settings.value('portraits/mode', 'anime')
        if self._mode not in MODELS:
            self._mode = 'anime'
        self._speed = backend.settings.value('portraits/speed', 'normal')
        if self._speed not in ANALYSIS_PROFILES:
            self._speed = 'normal'
        self._queue = []
        self._inflight = None
        self._revisions = {}
        self._characters = [{'id': c.id, 'name': c.name} for c in backend.editor.document.characters]
        self._results = PortraitResultsModel(self)
        self._filtered = PortraitResultsFilter(self, self._results)
        self.changed.connect(self._results.sync)
        backend.changed.connect(self._sync_characters)
        self._timer = QTimer(self, interval=200)
        self._timer.timeout.connect(self._send_next)
        backend.documentReplaced.connect(self.reset)
        backend.changed.connect(self.changed)
        backend.media_controller.changed.connect(self.changed)
        backend.online.changed.connect(self.changed)
        backend.online.glossary_session.changed.connect(self.changed)
        backend.online.glossary_session.changed.connect(self.reconcilePending)
        backend.online.changed.connect(self.reconcilePending)

    @Property(bool, notify=changed)
    def busy(self):
        return self._job is not None or bool(self._queue) or self._inflight is not None

    @Property(str, notify=changed)
    def status(self):
        return self._status

    @Property(float, notify=changed)
    def progress(self):
        return self._progress

    @Property(bool, notify=showUnnamedChanged)
    def showUnnamed(self):
        return self._show_unnamed

    @Slot(bool)
    def setShowUnnamed(self, show):
        if show != self._show_unnamed:
            self._filtered.beginFilterChange()
            self._show_unnamed = show
            self._filtered.endFilterChange(QSortFilterProxyModel.Direction.Rows)
            self.showUnnamedChanged.emit()
            self.changed.emit()

    @Property(bool, notify=changed)
    def adding(self):
        return self._activity == 'adding'

    @Property(bool, notify=changed)
    def saveVisible(self):
        return self._save_visible

    @Property(str, notify=changed)
    def saveStatus(self):
        return self._save_status

    @Property(float, notify=changed)
    def saveProgress(self):
        return self._save_progress

    def _save_feedback(self, message, progress=None):
        self._save_visible = True
        self._save_status = self._status = message
        if progress is not None:
            self._save_progress = max(0., min(1., progress))
        self.changed.emit()

    @Property(str, notify=changed)
    def mode(self):
        return self._mode

    @Slot(str)
    def setMode(self, mode):
        if mode in MODELS and not self.busy and mode != self._mode:
            self._mode = mode
            self.backend.settings.setValue('portraits/mode', mode)
            self.reset()

    @Property(str, notify=changed)
    def speed(self):
        return self._speed

    @Slot(str)
    def setSpeed(self, speed):
        if speed in ANALYSIS_PROFILES and not self.busy and speed != self._speed:
            self._speed = speed
            self.backend.settings.setValue('portraits/speed', speed)
            self.reset()

    @Property(str, constant=True)
    def modelDirectory(self):
        return str(shared_model_directory())

    @Property(str, notify=changed)
    def modelSize(self):
        return str(round(sum(m.size for m in MODELS.get(self._mode, MODELS['anime'])) / 1048576)) + ' МиБ'

    @Property('QVariantList', notify=charactersChanged)
    def characters(self):
        return self._characters + [{'id': key, 'name': name} for key, name in self._new_characters.items()]

    def _sync_characters(self):
        characters = [{'id': c.id, 'name': c.name} for c in self.backend.editor.document.characters]
        if characters != self._characters:
            self._characters = characters
            self.charactersChanged.emit()

    @Property(QObject, constant=True)
    def resultsModel(self):
        self._results.sync()
        return self._filtered

    @Slot(int, result=int)
    def visibleIndex(self, source_index):
        self._results.sync()
        return self._filtered.mapFromSource(self._results.index(source_index)).row()

    @Property('QVariantMap', notify=changed)
    def summary(self):
        rows = [r for r in self._rows if 'mergedInto' not in r]
        unnamed = sum(not r['cardId'] for r in rows)
        return {'total': len(rows) if self.showUnnamed else len(rows) - unnamed,
                'found': len(rows), 'unnamed': unnamed,
                'selected': sum(bool(r['checked'] and r['cardId'] and not r['applied'] and not r.get('pendingPortraitId')) for r in rows)}

    def _media_context(self):
        b = self.backend
        path = b.media_controller.path
        try:
            stat = Path(path).stat()
            return id(b.editor), path, stat.st_size, stat.st_mtime_ns, id(b.online.glossary_session.repository)
        except OSError:
            return None

    def _current(self):
        if self._snapshot is None or self._context != self._media_context():
            return False
        if self.backend.online.active:
            # Server portrait acknowledgements replace images/cards, but never
            # authorize using results after speaker/timing/character changes.
            doc = self.backend.editor.document
            pending_new = {r.get('pendingPortraitId') for r in self._rows if r['cardId'] in self._new_characters}
            expected_new = {e['id'] for e in self.backend.online.glossary_session.entries
                            if e['kind'] == 'character' and any(p['id'] in pending_new for p in e['data'].get('portraits', []))}
            return ([(c.id, c.start, c.end, c.character_id, c.comment) for c in doc.cues] ==
                    [(c.id, c.start, c.end, c.character_id, c.comment) for c in self._snapshot.cues]
                    and {c.id: c.name for c in doc.characters if c.id not in expected_new} == {c.id: c.name for c in self._snapshot.characters})
        return self.backend.editor.document == self._snapshot

    @Property(bool, notify=changed)
    def stale(self):
        return bool(self._rows) and not self._current()

    @Property(bool, notify=changed)
    def canAnalyze(self):
        b = self.backend
        return not self.busy and b.media_controller.hasVideo

    @Property(bool, notify=changed)
    def canCreateCharacter(self):
        online = self.backend.online
        return not self.busy and self._current() and (not online.active or
            (online.glossary_session.canEdit and not online.busy and not online.glossary_session.pending))

    @Property(bool, notify=changed)
    def canApply(self):
        online = self.backend.online
        writable = not online.active or (online.glossary_session.canEdit and not online.busy and not online.glossary_session.pending)
        return not self.busy and writable and self._current() and any(r['checked'] and r['cardId'] and not r['applied'] and not r.get('pendingPortraitId') and 'mergedInto' not in r for r in self._rows)

    @Property('QVariantList', notify=changed)
    def rows(self):
        result = []
        names = {c['id']: c['name'] for c in self.characters}
        for i, row in enumerate(self._rows):
            candidate = row['candidates'][row['variant']]
            result.append({k: row[k] for k in ('cardId', 'checked', 'confident', 'reason', 'appearances', 'applied')})
            result[-1]['pending'] = bool(row.get('pendingPortraitId'))
            result[-1].update(sourceIndex=i, merged='mergedInto' in row)
            result[-1]['newCharacter'] = row['cardId'] in self._new_characters
            result[-1].update(url=f'image://project/auto-portrait-{self._generation}-{i}-{row["variant"]}',
                              detailUrl=f'image://project/auto-portrait-full-{self._generation}-{i}-{row["variant"]}',
                              cardName=names.get(row['cardId'], 'Персонаж не определён'),
                              time=format_time(candidate['time']), variant=row['variant'] + 1, variants=len(row['candidates']))
        return result

    def preview_image(self, key):
        parts = key.split('-')
        try:
            generation, index, variant = map(int, parts[-3:])
            if generation == self._generation and index >= 0 and variant >= 0:
                candidate = self._rows[index]['candidates'][variant]
                if key.startswith('auto-portrait-full-'):
                    return crop_image(decode_image(candidate['source']), candidate['crop'])
                return candidate['preview']
        except (ValueError, IndexError):
            pass
        return QImage()

    @Slot()
    def open(self):
        if self.backend.flush() and self.backend.flushCard() and self.backend.ensureProject():
            self.requested.emit()

    @Slot()
    def analyze(self):
        b = self.backend
        if not self.canAnalyze or not b.flush() or not b.flushCard() or not b.ensureProject():
            return
        self.reset()
        self._context = self._media_context()
        self._snapshot = deepcopy(b.editor.document)
        self._revisions = {r['id']: r['revision'] for r in b.online.glossary_session.entries}
        cues = [{'id': c.id, 'start': c.start, 'end': c.end, 'character_id': c.character_id, 'comment': c.comment} for c in self._snapshot.cues]
        job = PortraitJob(b.media_controller.path, b.media_controller.duration, cues,
                          [asdict(c) for c in self._snapshot.characters], self._snapshot.images,
                          self._mode, shared_model_directory(), self._speed)
        self._job = job
        self._activity = 'analysis'
        token = self._generation
        job.signals.progress.connect(lambda progress, status: self._on_progress(token, progress, status))
        job.signals.result.connect(lambda result: self._on_result(token, result))
        job.signals.finished.connect(lambda result: self._on_finished(token, result))
        self._status = 'Готовим поиск лиц в видео…'
        self.changed.emit()
        QThreadPool.globalInstance().start(job)

    def _on_progress(self, token, progress, status):
        if token == self._generation:
            self._progress, self._status = progress, status
            self.changed.emit()

    def _on_result(self, token, result):
        if token != self._generation:
            return
        if not self._current():
            self._status = 'Документ или видео изменились. Повторите поиск лиц.'
        else:
            self._rows = combine_named_rows(result['rows'])
            named = sum(bool(r['cardId']) for r in self._rows)
            self._status = f'Найдено персонажей с именем: {named}. Проверьте портреты перед добавлением.'
            if not self._rows:
                self._status = 'Лица не найдены. Попробуйте другой тип видео или проверьте таймкоды.'
        self.changed.emit()

    def _on_finished(self, token, result):
        if token == self._generation:
            self._job = None
            self._activity = ''
            if result['cancelled']:
                self._status = 'Поиск остановлен'
            elif result['error']:
                self._status = 'Не удалось найти портреты: ' + result['error']
            self.changed.emit()

    @Slot(int, str)
    def assign(self, index, card_id):
        if not self.busy and 0 <= index < len(self._rows) and card_id in ['', *[c['id'] for c in self.characters]]:
            row = self._rows[index]
            if not row['applied'] and not row.get('pendingPortraitId') and 'mergedInto' not in row:
                target = next((i for i, r in enumerate(self._rows) if i != index and card_id and r['cardId'] == card_id and 'mergedInto' not in r), None)
                if target is not None:
                    existing = self._rows[target]
                    existing['candidates'] = unique_candidates(existing['candidates'] + row['candidates'])
                    existing['appearances'] += row['appearances']
                    if not existing['applied'] and not existing.get('pendingPortraitId'):
                        existing['checked'] = True
                    row.update(mergedInto=target, checked=False)
                    self._status = 'Кадры добавлены в варианты портрета выбранного персонажа.'
                    self.changed.emit()
                    self.selectionRequested.emit(target)
                    return
                row.update(cardId=card_id, checked=bool(card_id), confident=False, reason='Имя выбрано вручную.')
                self.changed.emit()

    @Slot(int, str, result=bool)
    def createCharacter(self, index, name):
        name = name.strip()
        if not name or '\n' in name or '\r' in name or not self.canCreateCharacter or not 0 <= index < len(self._rows):
            return False
        row = self._rows[index]
        if row['applied'] or row.get('pendingPortraitId') or 'mergedInto' in row:
            return False
        existing = next((c for c in self.characters if c['name'].casefold() == name.casefold()), None)
        if existing:
            self.assign(index, existing['id'])
            return True
        if self.backend.online.active and any(e['kind'] == 'character' and e['data']['name'].casefold() == name.casefold()
                for e in self.backend.online.glossary_session.entries):
            self._status = 'Такой персонаж уже есть в общем глоссарии. Проверьте его карточку и архив.'
            self.changed.emit()
            return False
        card_id = identity('char')
        self._new_characters[card_id] = name
        self.charactersChanged.emit()
        self.assign(index, card_id)
        self._status = f'Персонаж «{name}» будет создан вместе с портретом при добавлении в глоссарий.'
        self.changed.emit()
        return True

    @Slot(int, bool)
    def check(self, index, checked):
        if not self.busy and 0 <= index < len(self._rows) and not self._rows[index]['applied'] and not self._rows[index].get('pendingPortraitId') and 'mergedInto' not in self._rows[index]:
            self._rows[index]['checked'] = checked and bool(self._rows[index]['cardId'])
            self.changed.emit()

    @Slot()
    def clearSelection(self):
        if not self.busy:
            for row in self._rows:
                row['checked'] = False
            self.changed.emit()

    @Slot(int)
    def nextVariant(self, index):
        if not self.busy and 0 <= index < len(self._rows) and not self._rows[index].get('pendingPortraitId') and 'mergedInto' not in self._rows[index]:
            row = self._rows[index]
            if row['applied']:
                row.setdefault('savedCandidates', set()).add(candidate_key(row['candidates'][row['variant']]))
            row['variant'] = (row['variant'] + 1) % len(row['candidates'])
            row['applied'] = candidate_key(row['candidates'][row['variant']]) in row.get('savedCandidates', ())
            if row['applied']:
                row['checked'] = False
            self.changed.emit()

    @Slot(int)
    def seek(self, index):
        if self._current() and 0 <= index < len(self._rows):
            row = self._rows[index]
            self.backend.media_controller.seek(row['candidates'][row['variant']]['time'])

    def _mark_applied(self, row):
        row.setdefault('savedCandidates', set()).add(candidate_key(row['candidates'][row['variant']]))
        row.update(applied=True, checked=False, pendingPortraitId='')

    @Slot(bool, result=bool)
    def apply(self, replace_primary=False):
        b = self.backend
        if self.busy:
            return False
        if not b.flush() or not b.flushCard():
            self._save_feedback('Не удалось сохранить правки документа. Проверьте их перед добавлением портретов.')
            return False
        if not self._current():
            self._save_feedback('Документ или видео изменились. Повторите поиск лиц перед добавлением.')
            return False
        if not self.canApply:
            online = b.online
            if online.active and (online.busy or online.glossary_session.pending):
                message = 'Дождитесь отправки предыдущего изменения в общем глоссарии.'
            elif online.active and not online.glossary_session.canEdit:
                message = 'В этом проекте нет прав на добавление портретов.'
            else:
                message = 'Отметьте портреты для добавления и выберите для них имена.'
            self._save_feedback(message)
            return False
        selected = [i for i, r in enumerate(self._rows) if r['checked'] and r['cardId'] and not r['applied']
                    and not r.get('pendingPortraitId') and 'mergedInto' not in r]
        ids = [self._rows[i]['cardId'] for i in selected]
        if len(ids) != len(set(ids)):
            self._save_feedback('Для одного имени выбрано несколько портретов. Оставьте один вариант для каждого персонажа.')
            return False
        choices = [(i, self._rows[i]['cardId'], dict(self._rows[i]['candidates'][self._rows[i]['variant']])) for i in selected]
        self._saving_online = b.online.active
        self._replace_primary = replace_primary
        self._save_total, self._save_done = len(choices), 0
        self._prepared_records = {}
        self._activity = 'adding'
        self._save_feedback(f'Готовим портреты к добавлению: 0 из {self._save_total}', 0)
        job = PreparePortraitsJob(choices, self._context[1])
        self._job = job
        token = self._generation
        job.signals.progress.connect(lambda progress, status: self._on_save_progress(token, progress, status))
        job.signals.result.connect(lambda records: self._on_save_prepared(token, records))
        job.signals.finished.connect(lambda outcome: self._on_save_finished(token, outcome))
        self.changed.emit()
        QThreadPool.globalInstance().start(job)
        return True

    def _on_save_progress(self, token, progress, status):
        if token == self._generation:
            self._save_feedback(status, progress * (.45 if self._saving_online else .85))

    def _on_save_prepared(self, token, records):
        if token != self._generation or self._job.cancelled.is_set():
            return
        b = self.backend
        if not b.flush() or not b.flushCard() or not self._current():
            self._activity = ''
            self._save_feedback('Добавление остановлено: документ или видео изменились. Повторите поиск.')
            return
        if self._saving_online:
            self._prepared_records = {i: (portrait, images) for i, _, portrait, images in records}
            self._queue = [i for i, _, _, _ in records]
            self._save_feedback(f'Отправляем портреты в общий глоссарий: 0 из {self._save_total}', .45)
            self._timer.start()
            return
        self._save_feedback(f'Добавляем в глоссарий: {self._save_total} портретов…', .9)
        had_portraits = any(c.primary for c in b.editor.document.characters if c.id in {r[1] for r in records})
        def edit(doc):
            for _, card_id, portrait, images in records:
                if card_id in self._new_characters:
                    name = self._new_characters[card_id]
                    if any(c.name.casefold() == name.casefold() for c in doc.characters):
                        raise ValueError('Персонаж с таким именем уже существует')
                    doc.characters.append(CharacterCard(card_id, name, export_name=name))
                card = next(c for c in doc.characters if c.id == card_id)
                card.portraits.append(portrait)
                doc.images.update(images)
                if self._replace_primary or not card.primary:
                    card.primary = portrait['id']
        try:
            ok = b._guard(lambda: b.editor.transact('Автозаполнение портретов', edit))
            if ok:
                for index, _, _, _ in records:
                    self._mark_applied(self._rows[index])
                for _, card_id, _, _ in records:
                    self._new_characters.pop(card_id, None)
                self.charactersChanged.emit()
                self._snapshot = deepcopy(b.editor.document)
                self._save_done = self._save_total
                message = f'Добавлено портретов: {self._save_done} из {self._save_total}. '
                if self._replace_primary:
                    message += 'Новые портреты назначены основными. '
                elif had_portraits:
                    message += 'Для заполненных карточек новые портреты добавлены в галерею. '
                message += 'Добавление можно отменить одним действием.'
                self._activity = ''
                self._save_feedback(message, 1)
            else:
                self._activity = ''
                self._save_feedback('Не удалось добавить портреты: ' + b.message)
        except (ValueError, OSError, KeyError, StopIteration) as exc:
            self._activity = ''
            self._save_feedback('Не удалось добавить портреты: ' + str(exc))

    def _on_save_finished(self, token, outcome):
        if token != self._generation:
            return
        cancelled = outcome['cancelled'] or (self._job is not None and self._job.cancelled.is_set())
        self._job = None
        if self._activity == 'adding' and not self._queue and self._inflight is None:
            self._activity = ''
            if cancelled:
                self._save_feedback('Добавление отменено. Портреты в глоссарии не изменены.')
            elif outcome['error']:
                self._save_feedback('Не удалось добавить портреты: ' + outcome['error'])
        self.changed.emit()

    def _stop_sending(self, message):
        self._queue = []
        self._inflight = None
        self._timer.stop()
        self._prepared_records = {}
        self._activity = ''
        self._save_feedback(message)

    def _saved_entry(self, row, portrait_id):
        entries = self.backend.online.glossary_session.entries
        if row['cardId'] in self._new_characters:
            return next((e for e in entries if e['kind'] == 'character' and
                         any(p['id'] == portrait_id for p in e['data'].get('portraits', []))), None)
        return next((e for e in entries if e['id'] == row['cardId']), None)

    def _adopt_created(self, row, entry):
        if row['cardId'] in self._new_characters and entry:
            self._new_characters.pop(row['cardId'])
            row['cardId'] = entry['id']
            card = next((c for c in self.backend.editor.document.characters if c.id == entry['id']), None)
            if card and all(c.id != card.id for c in self._snapshot.characters):
                self._snapshot.characters.append(deepcopy(card))
            self.charactersChanged.emit()

    def _send_next(self):
        try:
            self._send_next_checked()
        except (ValueError, OSError, KeyError, TypeError) as exc:
            self._stop_sending('Отправка портретов остановлена: ' + str(exc))

    def _send_next_checked(self):
        b = self.backend
        session = b.online.glossary_session
        if not self._current() or not b.online.active:
            self._stop_sending('Контекст проекта изменился. Отправка следующих портретов остановлена.')
            return
        if b.online.busy:
            return
        if self._inflight is not None:
            index, portrait_id = self._inflight
            if session.pending:
                self._stop_sending('Отправка приостановлена: ' + session.status + '. Повторите отправку в глоссарии; остальные результаты сохранены в этом окне.')
                return
            row = self._rows[index]
            entry = self._saved_entry(row, portrait_id)
            if row['cardId'] in self._new_characters and not entry:
                self._stop_sending('Портрет отправлен, но новая карточка ещё не получена с сервера. Обновите общий глоссарий; повторно создавать её не нужно.')
                return
            # Translators may submit proposals rather than directly alter the
            # approved card. A cleared durable outbox is the acknowledgement.
            self._mark_applied(row)
            self._adopt_created(row, entry)
            self._save_done += 1
            self._save_feedback(f'Отправлено портретов: {self._save_done} из {self._save_total}',
                                .45 + .55 * self._save_done / max(1, self._save_total))
            if entry:
                self._revisions[entry['id']] = entry['revision']
            self._inflight = None
        if not self._queue:
            self._save_progress = 1.
            self._stop_sending(f'Отправлено портретов в общий глоссарий: {self._save_done} из {self._save_total}.')
            return
        if session.pending or not session.canEdit:
            self._stop_sending('Дождитесь отправки предыдущего изменения и проверьте права в глоссарии.')
            return
        index = self._queue.pop(0)
        row = self._rows[index]
        entry = next((e for e in session.entries if e['id'] == row['cardId']), None)
        new_name = self._new_characters.get(row['cardId'], '')
        if not new_name and (not entry or entry['revision'] != self._revisions.get(row['cardId'])):
            self._stop_sending('Карточка на сервере изменилась. Повторите поиск перед отправкой.')
            return
        portrait, images = self._prepared_records.pop(index)
        portrait['make_primary'] = self._replace_primary
        self._inflight = (index, portrait['id'])
        if not session.save_portrait('' if new_name else row['cardId'], new_name, portrait, images):
            self._stop_sending('Не удалось сохранить портрет. Проверьте состояние общего глоссария.')
            return
        row.update(checked=False, pendingPortraitId=portrait['id'])
        self._save_feedback(f'Отправляем портрет {self._save_done + 1} из {self._save_total}…')

    @Slot()
    def reconcilePending(self):
        """Do not recreate an operation after an uncertain network outcome."""
        session = self.backend.online.glossary_session
        if self.busy or not self._current() or session.pending or self.backend.online.busy:
            return
        for row in self._rows:
            portrait_id = row.get('pendingPortraitId')
            if not portrait_id:
                continue
            entry = self._saved_entry(row, portrait_id)
            if entry and any(p['id'] == portrait_id for p in entry['data'].get('portraits', [])):
                self._mark_applied(row)
                self._adopt_created(row, entry)
        self.changed.emit()

    @Slot()
    def cancel(self):
        if self._job:
            self._job.cancel()
        if self._queue or self._inflight:
            self._stop_sending('Отправка следующих портретов остановлена. Уже отправленное изменение обрабатывается в глоссарии.')

    @Slot()
    def reset(self):
        self.cancel()
        self._generation += 1
        self._job = None
        self._rows = []
        if self._new_characters:
            self._new_characters.clear()
            self.charactersChanged.emit()
        self._snapshot = self._context = None
        self._status = ''
        self._progress = 0.
        self._activity = ''
        self._save_visible = False
        self._save_status = ''
        self._save_progress = 0.
        self._prepared_records = {}
        self.changed.emit()

    def shutdown(self):
        self.reset()
