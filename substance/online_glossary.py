"""Project glossary forms and conflicts independent of episode document writes."""
from copy import deepcopy
from PySide6.QtCore import QObject, Property, Signal, Slot


class OnlineGlossary(QObject):
    changed = Signal()

    def __init__(self, online):
        super().__init__(online)
        self.online = online
        self.repository = None
        self._error = ''

    def attach(self, repository):
        self.repository = repository
        self._error = ''
        self.changed.emit()

    @Property(bool, notify=changed)
    def supported(self):
        return self.repository is not None

    @Property(bool, notify=changed)
    def pending(self):
        return bool(self.repository and self.repository.pending)

    @Property(bool, notify=changed)
    def canRestore(self):
        return bool(self.pending and self.repository.state['rejected'])

    @Property(bool, notify=changed)
    def canEdit(self):
        project = self.online._project_state
        return self.supported and not project.get('archived') and bool(project.get('server_admin') or
            set(project.get('roles', [])).intersection({'admin', 'chief_editor', 'editor', 'translator'}))

    @Property(bool, notify=changed)
    def canApprove(self):
        project = self.online._project_state
        return self.canEdit and bool(project.get('server_admin') or
            set(project.get('roles', [])).intersection({'admin', 'chief_editor', 'editor'}))

    @Property(str, notify=changed)
    def status(self):
        return self._error or ('Сохранено на компьютере · ожидает отправки' if self.pending else '')

    @Property('QVariantList', notify=changed)
    def entries(self):
        return self.repository.items if self.repository else []

    @Property('QVariantMap', notify=changed)
    def draft(self):
        return deepcopy(self.repository.state['draft']) if self.repository else {}

    @Property('QVariantMap', notify=changed)
    def serverEntry(self):
        return next((r for r in self.entries if r['id'] == self.draft.get('id')), {})

    @Property(bool, notify=changed)
    def stale(self):
        return bool(self.serverEntry and self.serverEntry['revision'] != self.draft.get('base_revision'))

    @Property('QVariantList', notify=changed)
    def conflicts(self):
        draft, row = self.draft, self.serverEntry
        if not row or not self.stale:
            return []
        base, mine, current = draft.get('base_data', {}), draft.get('data', {}), row['data']
        labels = {'name': 'Имя', 'export_name': 'Имя в экспорте', 'aliases': 'Алиасы',
                  'description': 'Описание', 'speech': 'Особенности речи', 'pronunciation': 'Произношение',
                  'relationships': 'Отношения', 'notes': 'Заметки', 'translation': 'Перевод',
                  'category': 'Категория', 'alternatives': 'Допустимые варианты', 'forbidden': 'Нежелательные варианты',
                  'example': 'Пример', 'status': 'Статус', 'archived': 'Архив', 'portraits': 'Портреты',
                  'primary': 'Основной портрет', 'extras': 'Дополнительные поля'}
        return [{'field': k, 'title': labels.get(k, k), 'base': str(base.get(k, '')), 'mine': str(v), 'server': str(current.get(k, ''))}
                for k, v in mine.items() if v != base.get(k) and current.get(k) != base.get(k) and current.get(k) != v]

    @Slot(str, str, result=bool)
    def begin(self, entry_id, kind):
        if not self.repository or self.pending or self.draft:
            return False
        row = next((r for r in self.entries if r['id'] == entry_id), None)
        if entry_id and not row:
            return False
        draft = {'id': entry_id, 'kind': row['kind'] if row else kind,
                 'base_revision': row['revision'] if row else 0,
                 'base_data': deepcopy(row['data']) if row else {},
                 'data': deepcopy(row['data']) if row else {'name': '', 'status': 'draft', 'archived': False}}
        return self.saveDraft(draft)

    @Slot('QVariantMap', result=bool)
    def saveDraft(self, draft):
        if not self.repository:
            return False
        try:
            self.repository.save_draft(draft)
            self.changed.emit()
            return True
        except (ValueError, OSError) as exc:
            self._error = 'Не удалось сохранить черновик: ' + str(exc)
            self.changed.emit()
            return False

    @Slot(result=bool)
    def send(self):
        if not self.canEdit or self.pending or self.online.busy:
            return False

        try:
            draft = self.draft
            row = self.serverEntry
            proposal = bool(row and row['data'].get('status') == 'approved' and not self.canApprove)
            if not self.canApprove and draft.get('data', {}).get('status') == 'approved' and not proposal:
                raise ValueError('Утверждать карточки может редактор или главред')
            self.repository.enqueue(proposal)
            self._error = ''
            self.changed.emit()
            self.refresh()
            return True
        except (ValueError, OSError) as exc:
            self._error = str(exc)
            self.changed.emit()
            return False

    def _portrait_draft(self, card_id, new_name=''):
        if not self.canEdit:
            raise ValueError('Нет прав на изменение портретов в этом проекте')
        if self.online.busy:
            raise ValueError('Дождитесь завершения синхронизации и сохраните портрет ещё раз')
        if self.pending:
            raise ValueError('Предыдущее изменение глоссария ещё не отправлено. '
                             'Повторите отправку и сохраните портрет ещё раз')
        row = next((r for r in self.entries if r['id'] == card_id and r['kind'] == 'character'), None)
        if card_id and not row:
            raise ValueError('Карточка персонажа недоступна. Обновите онлайн-глоссарий')
        name = new_name.strip()
        if not card_id and (not name or any(r['kind'] == 'character' and r['data']['name'] == name for r in self.entries)):
            raise ValueError('Введите новое уникальное имя персонажа')
        return {'id': card_id, 'kind': 'character', 'base_revision': row['revision'] if row else 0,
                'base_data': deepcopy(row['data']) if row else {},
                'data': deepcopy(row['data']) if row else {
                    'name': name, 'export_name': name, 'status': 'draft', 'archived': False,
                    'portraits': [], 'primary': None, 'extras': {}}}

    def _send_portrait(self, draft):
        # Inspecting a card creates a durable form too. Keep that form (including
        # real edits and its base revision) separate from this portrait operation.
        row = next((r for r in self.entries if r['id'] == draft['id']), None)
        proposal = bool(row and row['data'].get('status') == 'approved' and not self.canApprove)
        self.repository.enqueue(proposal, draft=draft)
        self._error = ''
        self.changed.emit()
        self.refresh()
        self.online.backend._message = 'Портрет сохранён на компьютере · отправляется в проект'
        self.online.backend.changed.emit()
        return True

    def save_portrait(self, card_id, new_name, portrait, images):
        try:
            draft = self._portrait_draft(card_id, new_name)
            data = draft['data']
            portraits = data.setdefault('portraits', [])
            frame = deepcopy(portrait.get('frame', {}))
            frame['time_ms'] = portrait.get('time', frame.get('time_ms', 0))
            saved = {k: deepcopy(portrait[k]) for k in ('id', 'source', 'image', 'crop')}
            saved['frame'] = frame
            index = next((i for i, p in enumerate(portraits) if p['id'] == saved['id']), None)
            if index is None:
                portraits.append(saved)
            else:
                portraits[index] = saved
            if portrait.get('make_primary') or not data.get('primary'):
                data['primary'] = saved['id']
            draft['images'] = deepcopy(images)
            return self._send_portrait(draft)
        except (ValueError, OSError) as exc:
            self.online.backend.show_error(str(exc))
            return False

    def portrait_action(self, card_id, portrait_id, action):
        try:
            draft = self._portrait_draft(card_id)
            data = draft['data']
            if not any(p['id'] == portrait_id for p in data.get('portraits', [])):
                raise ValueError('Портрет не найден')
            if action == 'primary':
                data['primary'] = portrait_id
            elif action == 'delete':
                data['portraits'] = [p for p in data['portraits'] if p['id'] != portrait_id]
                if data.get('primary') == portrait_id:
                    data['primary'] = data['portraits'][0]['id'] if data['portraits'] else None
            else:
                raise ValueError('Неизвестное действие с портретом')
            return self._send_portrait(draft)
        except (ValueError, OSError) as exc:
            self.online.backend.show_error(str(exc))
            return False

    @Slot(result=bool)
    def discardDraft(self):
        return self.saveDraft({})

    @Slot(result=bool)
    def restorePending(self):
        if not self.canRestore or self.online.busy:
            return False
        try:
            self.repository.restore_pending()
            self._error = ''
            self.changed.emit()
            return True
        except (ValueError, OSError) as exc:
            self._error = str(exc)
            self.changed.emit()
            return False

    @Slot('QVariantMap', result=bool)
    def rebase(self, choices):
        if not self.repository or self.pending or self.online.busy:
            return False
        try:
            self.repository.rebase(choices)
            self._error = ''
            self.changed.emit()
            return True
        except (ValueError, OSError) as exc:
            self._error = str(exc)
            self.changed.emit()
            return False

    def poll(self):
        if not self.repository:
            return '', None, None
        try:
            self.repository.sync()
            error = ''
        except Exception as exc:
            error = str(exc)
            try:
                self.repository.refresh()
            except Exception:
                pass
        try:
            rows = self.repository.items
            images = self.online._images(self.repository.repository.client, self.online.context, rows)
            return error, rows, images
        except Exception as exc:
            return error or str(exc), None, None

    def updated(self, outcome):
        self._error, rows, images = outcome
        if rows is not None:
            self.online.apply_glossary(rows, images)
        self.changed.emit()

    @Slot()
    def refresh(self):
        if not self.repository or self.online.busy:
            return
        def operation():
            project = self.repository.repository.client.request('GET', f"/v1/projects/{self.online.context['project_id']}")
            return project, self.poll()
        def done(result):
            project, outcome = result
            self.online._update_project(project)
            self.updated(outcome)
        self.online._run(operation, done)

    @Slot()
    def retry(self):
        if not self.repository or self.online.busy:
            return
        try:
            self.repository.retry()
            self.refresh()
        except OSError as exc:
            self._error = str(exc)
            self.changed.emit()
