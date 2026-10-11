"""Transactional edits, history and quality checks. No dependency on Qt."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import dataclass
from typing import Callable
import re

from .document import Cue, Document, identity, plain_text
from .timecode import frame_time


@dataclass
class HistoryEntry:
    label: str
    before: Document
    after: Document
    before_revision: int
    after_revision: int


class Editor:
    def __init__(self, document: Document | None = None):
        self.document = document or Document()
        self.undo_stack: list[HistoryEntry] = []
        self.redo_stack: list[HistoryEntry] = []
        self.revision = self.saved_revision = 0
        self._serial = 0

    @property
    def dirty(self) -> bool:
        return self.revision != self.saved_revision

    def mark_saved(self):
        self.saved_revision = self.revision

    def transact(self, label: str, edit: Callable[[Document], None]) -> bool:
        before = self.document
        after = deepcopy(before)
        edit(after)
        after.validate()
        if after == before:
            return False
        self._serial += 1
        self.undo_stack.append(HistoryEntry(label, before, after, self.revision, self._serial))
        # Snapshots share consecutive revisions; bounded history keeps memory predictable.
        max_entries = max(4, min(80, 200000 // max(1, len(after.cues))))
        self.undo_stack = self.undo_stack[-max_entries:]
        self.redo_stack.clear()
        self.document = after
        self.revision = self._serial
        return True

    def undo(self) -> str:
        if not self.undo_stack:
            return ""
        entry = self.undo_stack.pop()
        self.redo_stack.append(entry)
        self.document, self.revision = entry.before, entry.before_revision
        return entry.label

    def redo(self) -> str:
        if not self.redo_stack:
            return ""
        entry = self.redo_stack.pop()
        self.undo_stack.append(entry)
        self.document, self.revision = entry.after, entry.after_revision
        return entry.label

    def update(self, index: int, **values) -> bool:
        allowed = {"start", "end", "text", "translation", "character", "status", "comment"}
        if not set(values) <= allowed:
            raise ValueError("Неизвестное поле реплики")
        def apply(doc):
            cue = doc.cues[index]
            for key, value in values.items():
                setattr(cue, key, value)
            if "translation" in values:
                cue.extras.pop("authoring", None)
            if cue.extras.get("authoring"):
                related = [other for other in doc.cues if other is not cue and set(other.source_ids).intersection(cue.source_ids)]
                if related:
                    cue.extras.pop("authoring", None)
                    for other in related:
                        other.extras.pop("authoring", None)
            if cue.extras.get("authoring"):
                cue.original = cue.text
                source = doc.source_lines[cue.source_ids[0]]
                source.update(text=cue.original, start=cue.start / 1000, end=cue.end / 1000, character=cue.character)
            if "start" in values or "end" in values:
                cue.extras.pop("untimed", None)
        return self.transact("Изменение реплики", apply)

    def add(self, after: int = -1, position: int | None = None) -> int:
        def apply(doc):
            start = position if position is not None else (doc.cues[after].end if 0 <= after < len(doc.cues) else 0)
            cue = Cue(start=start, end=start + 2000, extras={"authoring": True})
            if doc.cues:
                cue.field_order = list(doc.cues[max(0, after)].field_order)
                cue.ass_fields = dict(doc.cues[max(0, after)].ass_fields)
            doc.register_source(cue)
            doc.cues.insert(after + 1, cue)
        self.transact("Добавление реплики", apply)
        return after + 1

    def delete(self, indices: list[int]) -> None:
        indices = set(indices)
        self.transact("Удаление реплик", lambda d: setattr(d, "cues", [c for i, c in enumerate(d.cues) if i not in indices]))

    def duplicate(self, indices: list[int]) -> int:
        last = -1
        def apply(doc):
            nonlocal last
            for index in sorted(set(indices), reverse=True):
                copy = deepcopy(doc.cues[index])
                copy.id = identity("frag")
                copy.status = "draft"
                doc.cues.insert(index + 1, copy)
            last = max(indices) + len(set(indices)) if indices else -1
        self.transact("Дублирование реплик", apply)
        return last

    def split(self, index: int, cursor: int, position: int | None = None, *, translation_mode: bool = False) -> None:
        def apply(doc):
            cue = doc.cues[index]
            text = cue.output_text
            if not 0 < cursor < len(text):
                raise ValueError("Поставьте курсор внутри текста реплики")
            when = position if position is not None and cue.start < position < cue.end else cue.start + max(1, round((cue.end - cue.start) * cursor / len(text)))
            if not cue.start < when < cue.end:
                raise ValueError("Интервал слишком короткий для разделения")
            second = deepcopy(cue)
            second.id = identity("frag")
            second.start, cue.end = when, when
            cue.status = second.status = "draft"
            cue.extras.pop("authoring", None)
            second.extras.pop("authoring", None)
            first_text, second_text = text[:cursor].rstrip(), text[cursor:].lstrip()
            if translation_mode or cue.translation is not None:
                cue.translation, second.translation = first_text, second_text
            else:
                cue.text, second.text = first_text, second_text
            doc.cues.insert(index + 1, second)
        self.transact("Разделение реплики", apply)

    def merge(self, indices: list[int]) -> None:
        indices = sorted(set(indices))
        if len(indices) < 2 or indices != list(range(indices[0], indices[-1] + 1)):
            raise ValueError("Выберите две или больше соседних реплик")
        def apply(doc):
            cues = [doc.cues[i] for i in indices]
            result = deepcopy(cues[0])
            result.id = identity("frag")
            result.source_ids = list(dict.fromkeys(s for c in cues for s in c.source_ids))
            result.start, result.end = min(c.start for c in cues), max(c.end for c in cues)
            result.original = r"\N".join(doc.source_lines[s]["text"] for s in result.source_ids)
            result.extras.pop("authoring", None)
            result.text = r"\N".join(c.text for c in cues)
            result.translation = r"\N".join(c.output_text for c in cues) if any(c.translation is not None for c in cues) else None
            result.status = "draft"
            doc.cues[indices[0]:indices[-1] + 1] = [result]
        self.transact("Объединение реплик", apply)

    def shift(self, indices: list[int], delta: int, edges: str = "both") -> None:
        if edges not in ("both", "start", "end"):
            raise ValueError("Некорректный режим сдвига")
        def apply(doc):
            for i in indices:
                cue = doc.cues[i]
                if edges in ("both", "start"):
                    cue.start += delta
                if edges in ("both", "end"):
                    cue.end += delta
                cue.extras.pop("untimed", None)
        self.transact("Сдвиг времени", apply)

    def batch(self, indices: list[int], action: str, value=None) -> None:
        def apply(doc):
            if action == "sort":
                doc.cues.sort(key=lambda c: (c.start, c.end))
                return
            for i in indices:
                c = doc.cues[i]
                if action == "status":
                    c.status = value
                elif action == "character":
                    c.character = str(value)
                elif action == "comment":
                    c.comment = bool(value)
                elif action == "frames":
                    c.start, c.end = frame_time(c.start, doc.fps), frame_time(c.end, doc.fps)
                    if c.end <= c.start:
                        c.end = c.start + max(1, round(1000 / doc.fps))
                elif action == "lead":
                    c.start = max(0, c.start - int(value[0]))
                    c.end += int(value[1])
                elif action == "remove_overlap":
                    if i + 1 < len(doc.cues) and not doc.cues[i + 1].comment:
                        next_start = doc.cues[i + 1].start
                        if c.start < next_start < c.end:
                            c.end = next_start
                else:
                    raise ValueError("Неизвестная пакетная операция")
        self.transact("Обработка реплик", apply)

    def replace(self, search: str, replacement: str, indices: list[int], *, regex=False, case_sensitive=False, originals=False) -> int:
        if not search:
            return 0
        if originals:
            raise ValueError("Исходный текст перевода неизменяем. Заменять можно рабочий текст.")
        pattern = re.compile(search if regex else re.escape(search), 0 if case_sensitive else re.IGNORECASE)
        count = 0
        def apply(doc):
            nonlocal count
            for i in indices:
                c = doc.cues[i]
                value, n = pattern.subn(replacement if regex else lambda _: replacement, c.output_text)
                if n:
                    if c.translation is not None:
                        c.translation = value
                    else:
                        c.text = value
                    if c.status == "done":
                        c.status = "review"
                    count += n
        self.transact("Поиск и замена", apply)
        return count


def quality(cue: Cue, *, next_cue: Cue | None = None, cps_limit=20, line_limit=42, line_count_limit=2) -> dict:
    text = plain_text(cue.output_text)
    cps = len(text.replace("\n", "")) * 1000 / max(1, cue.end - cue.start)
    lines = text.splitlines() or [""]
    messages = []
    if cue.end == cue.start and not cue.comment:
        messages.append("Нулевой интервал")
    if cue.extras.get("untimed"):
        messages.append("Тайминг ещё не задан")
    if not text.strip() and not cue.comment:
        messages.append("Пустая реплика")
    if cps > cps_limit:
        messages.append(f"Скорость чтения: {cps:.1f} зн/с")
    if max(map(len, lines)) > line_limit:
        messages.append(f"Строка длиннее {line_limit} знаков")
    if len(lines) > line_count_limit:
        messages.append(f"Больше {line_count_limit} строк")
    if next_cue and not cue.comment and not next_cue.comment and cue.end > next_cue.start and cue.start < next_cue.end:
        messages.append("Пересечение с соседней репликой")
    if cue.comment:
        messages = []
    return {"cps": round(cps, 1), "characters": len(text.replace("\n", "")), "maxLine": max(map(len, lines)), "messages": messages, "warning": bool(messages)}
