"""Project-only records and transactional editing, independent of Qt."""
from dataclasses import dataclass, field as dc_field, fields
from datetime import datetime, timezone
from copy import deepcopy
import base64
import hashlib


def timestamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@dataclass
class ReviewEntry:
    id: str
    kind: str = 'note'
    cue_ids: list[str] = dc_field(default_factory=list)
    text: str = ''
    created: str = dc_field(default_factory=timestamp)
    updated: str = dc_field(default_factory=timestamp)
    state: str = 'open'
    field: str = 'text'
    base: str = ''
    replacement: str = ''
    context: str = ''
    invalidated: bool = False
    extras: dict = dc_field(default_factory=dict)


@dataclass
class CharacterCard:
    id: str
    name: str
    aliases: list[str] = dc_field(default_factory=list)
    export_name: str = ''
    description: str = ''
    speech: str = ''
    notes: str = ''
    portraits: list[dict] = dc_field(default_factory=list)
    primary: str = ''
    extras: dict = dc_field(default_factory=dict)


def record_from_dict(cls, item):
    if not isinstance(item, dict):
        raise ValueError('Некорректная запись проекта')
    known = {f.name for f in fields(cls)} - {'extras'}
    extra = deepcopy(item.get('extras', {}))
    extra.update({k: deepcopy(v) for k, v in item.items() if k not in known and k != 'extras'})
    return cls(**{k: deepcopy(v) for k, v in item.items() if k in known}, extras=extra)


def asset_id(encoded):
    return 'img_' + hashlib.sha256(base64.b64decode(encoded, validate=True)).hexdigest()


def validate_project(doc):
    if not isinstance(doc.reviews, list) or not isinstance(doc.characters, list) or not isinstance(doc.images, dict) or not isinstance(doc.review_settings, dict):
        raise ValueError('Некорректные данные проекта')
    for records in (doc.reviews, doc.characters):
        ids = [r.id for r in records]
        if any(not isinstance(v, str) or not v for v in ids) or len(set(ids)) != len(ids):
            raise ValueError('Некорректные идентификаторы записей проекта')
    # Immutable asset strings are shared by undo snapshots; validate their bytes
    # once per object, so typing does not repeatedly decode an entire gallery.
    verified_images = getattr(doc, "_verified_images", {})
    for key, encoded in doc.images.items():
        if verified_images.get(key) is encoded:
            continue
        if not isinstance(encoded, str) or len(encoded) > 26_000_000 or asset_id(encoded) != key:
            raise ValueError('Некорректное изображение проекта')
        raw = base64.b64decode(encoded, validate=True)
        if not raw.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff')):
            raise ValueError('Неподдерживаемый формат изображения проекта')
    doc._verified_images = dict(doc.images)
    for card in doc.characters:
        if not isinstance(card.name, str) or not card.name.strip():
            raise ValueError('У персонажа должно быть имя')
        if not all(isinstance(v, str) for v in (card.export_name, card.description, card.speech, card.notes)) or not isinstance(card.aliases, list) or not all(isinstance(v, str) for v in card.aliases):
            raise ValueError('Некорректная карточка персонажа')
        ids = [p.get('id') for p in card.portraits]
        if len(ids) != len(set(ids)) or (card.primary and card.primary not in ids):
            raise ValueError('Некорректный основной портрет')
        for p in card.portraits:
            if not p.get('id') or p.get('source') not in doc.images or p.get('image') not in doc.images:
                raise ValueError('Отсутствует изображение персонажа')
            crop = p.get('crop', [])
            if len(crop) != 4 or any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in crop):
                raise ValueError('Некорректная обрезка')
            x, y, w, h = crop
            if not (0 <= x < 1 and 0 <= y < 1 and 0 < w <= 1 and 0 < h <= 1 and x+w <= 1.000001 and y+h <= 1.000001):
                raise ValueError('Обрезка выходит за границы изображения')
            if not isinstance(p.get('media_path', ''), str) or not isinstance(p.get('time', 0), int):
                raise ValueError('Некорректный источник портрета')
    char_ids = {c.id for c in doc.characters}
    if any(c.character_id and c.character_id not in char_ids for c in doc.cues):
        raise ValueError('Реплика ссылается на отсутствующего персонажа')
    for entry in doc.reviews:
        allowed = ('open', 'resolved') if entry.kind == 'note' else ('open', 'applied', 'rejected')
        if entry.kind not in ('note', 'proposal') or entry.state not in allowed or entry.field not in ('text', 'translation'):
            raise ValueError('Некорректное замечание')
        if not isinstance(entry.cue_ids, list) or not all(isinstance(v, str) for v in entry.cue_ids) or not isinstance(entry.invalidated, bool):
            raise ValueError('Некорректная связь замечания')
        if not all(isinstance(v, str) for v in (entry.text, entry.base, entry.replacement, entry.context, entry.created, entry.updated)):
            raise ValueError('Некорректный текст замечания')
    if any(k in doc.review_settings and not isinstance(doc.review_settings[k], bool) for k in ('lineLength', 'readingSpeed', 'lineCount', 'overlaps')):
        raise ValueError('Некорректные настройки проверок')
    for key in ('cpsLimit', 'lineLimit', 'lineCountLimit'):
        if key in doc.review_settings and (type(doc.review_settings[key]) is not int or not 1 <= doc.review_settings[key] <= 1000):
            raise ValueError('Некорректный порог проверки')


def sync_characters(doc):
    """Give names stable IDs when a plain subtitle document becomes a project."""
    from .document import identity
    by_id = {c.id: c for c in doc.characters}
    for cue in doc.cues:
        if cue.character_id in by_id:
            cue.character = by_id[cue.character_id].name
        elif cue.character.strip():
            candidates = [c for c in doc.characters if cue.character == c.name]
            if not candidates:
                candidates = [c for c in doc.characters if cue.character in c.aliases]
            card = candidates[0] if len(candidates) == 1 else CharacterCard(identity('char'), cue.character, export_name=cue.character)
            if not candidates or len(candidates) != 1:
                doc.characters.append(card)
            cue.character_id = card.id
            cue.character = card.name


def rebind_reviews(doc, old_ids, new_ids):
    """Preserve notes through structural edits; replacements need human rebasing."""
    for entry in doc.reviews:
        if set(entry.cue_ids).intersection(old_ids):
            entry.cue_ids = list(dict.fromkeys([v for v in entry.cue_ids if v not in old_ids] + new_ids))
            if entry.kind == 'proposal' and entry.state == 'open':
                entry.invalidated = True


class ProjectEdits:
    def add_review(self, cue_id, text, *, replacement=None, target='text'):
        from .document import identity
        cue = next(c for c in self.document.cues if c.id == cue_id)
        if replacement is None and not text.strip():
            raise ValueError('Введите текст заметки')
        if target not in ('text', 'translation'):
            raise ValueError('Правки разрешены только для рабочего текста')
        entry = ReviewEntry(identity('review'), kind='note' if replacement is None else 'proposal', cue_ids=[cue_id], text=text, field=target, context=cue.output_text, base=getattr(cue, target) or '', replacement=replacement or '')
        if replacement is not None and entry.replacement == entry.base:
            raise ValueError('Предложение совпадает с текущим текстом')
        self.transact('Добавление заметки' if replacement is None else 'Предложение правки', lambda d: d.reviews.append(entry))
        return entry.id

    def edit_note(self, entry_id, text):
        if not text.strip():
            raise ValueError('Введите текст заметки')
        def edit(doc):
            entry = next(r for r in doc.reviews if r.id == entry_id)
            if entry.kind != 'note':
                raise ValueError('Это предложение правки')
            entry.text, entry.updated = text, timestamp()
        return self.transact('Изменение заметки', edit)

    def review_state(self, entry_id, state):
        def edit(doc):
            entry = next(r for r in doc.reviews if r.id == entry_id)
            allowed = ('open', 'resolved') if entry.kind == 'note' else ('rejected',)
            if state not in allowed or (entry.kind == 'proposal' and entry.state != 'open'):
                raise ValueError('Недопустимое действие с замечанием')
            entry.state, entry.updated = state, timestamp()
        return self.transact('Изменение замечания', edit)

    def delete_note(self, entry_id):
        def edit(doc):
            entry = next(r for r in doc.reviews if r.id == entry_id)
            if entry.kind != 'note':
                raise ValueError('Предложения сохраняются в истории')
            doc.reviews.remove(entry)
        return self.transact('Удаление заметки', edit)

    def apply_proposal(self, entry_id):
        def edit(doc):
            entry = next(r for r in doc.reviews if r.id == entry_id)
            cues = [c for c in doc.cues if c.id in entry.cue_ids]
            if entry.kind != 'proposal' or entry.state != 'open':
                raise ValueError('Предложение уже обработано')
            if entry.invalidated or len(cues) != 1 or (entry.field == 'text' and cues[0].translation is not None) or (getattr(cues[0], entry.field) or '') != entry.base:
                raise ValueError('Текст изменился. Пересмотрите предложение перед применением.')
            cue = cues[0]
            setattr(cue, entry.field, entry.replacement)
            self._sync_authored(doc, cue, {entry.field: entry.replacement})
            entry.state, entry.updated = 'applied', timestamp()
        return self.transact('Применение предложения правки', edit)

    def rebase_proposal(self, entry_id, cue_id, replacement, text):
        def edit(doc):
            entry = next(r for r in doc.reviews if r.id == entry_id)
            cue = next(c for c in doc.cues if c.id == cue_id)
            if entry.kind != 'proposal' or entry.state != 'open':
                raise ValueError('Предложение уже обработано')
            target = 'translation' if cue.translation is not None else entry.field
            if (getattr(cue, target) or '') == replacement:
                raise ValueError('Предложение совпадает с текущим текстом')
            entry.field = target
            entry.cue_ids, entry.base, entry.replacement, entry.text = [cue_id], getattr(cue, target) or '', replacement, text
            entry.invalidated, entry.updated = False, timestamp()
        return self.transact('Пересмотр предложения', edit)

    def save_character(self, card_id, name, aliases, export_name, description, speech, notes):
        from .document import identity
        name = name.strip()
        if not name:
            raise ValueError('Введите имя персонажа')
        card_id = card_id or identity('char')
        def edit(doc):
            if any(c.name == name and c.id != card_id for c in doc.characters):
                raise ValueError('Персонаж с таким именем уже существует')
            card = next((c for c in doc.characters if c.id == card_id), None)
            if card is None:
                card = CharacterCard(card_id, name)
                doc.characters.append(card)
            card.name, card.aliases, card.export_name = name, list(dict.fromkeys(v.strip() for v in aliases if v.strip())), export_name.strip() or name
            card.description, card.speech, card.notes = description, speech, notes
            for cue in doc.cues:
                if cue.character_id == card_id:
                    cue.character = name
        self.transact('Карточка персонажа', edit)
        return card_id

    def assign_character(self, indices, card_id):
        def edit(doc):
            card = next((c for c in doc.characters if c.id == card_id), None)
            if card_id and card is None:
                raise ValueError('Персонаж не найден')
            for i in indices:
                doc.cues[i].character_id = card_id
                doc.cues[i].character = card.name if card else ''
        return self.transact('Назначение персонажа', edit)

    def delete_character(self, card_id):
        def edit(doc):
            if any(c.character_id == card_id for c in doc.cues):
                raise ValueError('Сначала снимите назначение персонажа с его реплик')
            doc.characters = [c for c in doc.characters if c.id != card_id]
            self._prune_images(doc)
        return self.transact('Удаление персонажа', edit)

    @staticmethod
    def _prune_images(doc):
        used = {p[k] for c in doc.characters for p in c.portraits for k in ('source', 'image')}
        doc.images = {k: v for k, v in doc.images.items() if k in used}

    def save_portrait(self, card_id, portrait, images):
        def edit(doc):
            card = next(c for c in doc.characters if c.id == card_id)
            existing = next((i for i, p in enumerate(card.portraits) if p['id'] == portrait['id']), None)
            if existing is None:
                card.portraits.append(deepcopy(portrait))
            else:
                card.portraits[existing] = deepcopy(portrait)
            doc.images.update(images)
            if not card.primary or portrait.get('make_primary'):
                card.primary = portrait['id']
            self._prune_images(doc)
        return self.transact('Портрет персонажа', edit)

    def portrait_action(self, card_id, portrait_id, action):
        def edit(doc):
            card = next(c for c in doc.characters if c.id == card_id)
            if not any(p['id'] == portrait_id for p in card.portraits):
                raise ValueError('Портрет не найден')
            if action == 'primary':
                card.primary = portrait_id
            elif action == 'delete':
                card.portraits = [p for p in card.portraits if p['id'] != portrait_id]
                if card.primary == portrait_id:
                    card.primary = card.portraits[0]['id'] if card.portraits else ''
                self._prune_images(doc)
            else:
                raise ValueError('Неизвестное действие')
        return self.transact('Изменение портрета', edit)
