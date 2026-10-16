"""Conservative three-way merge of versioned episode snapshots.

Stable cue IDs allow independent field edits. Competing topology changes are
an explicit whole-sequence choice: never guess split/merge ancestry.
"""

from copy import deepcopy
import json

from .documents import validate_document

_MISSING = object()
LABELS = {
    "translation": "Перевод",
    "text": "Текст",
    "start": "Начало",
    "end": "Конец",
    "character_id": "Персонаж",
    "comment": "Комментарий",
    "original": "Оригинал",
    "source_ids": "Связь с исходником",
    "ass_fields": "Оформление",
    "metadata": "Метаданные",
    "extras": "Дополнительные данные",
    "styles": "Стили",
    "skeleton": "Структура ASS",
    "__substance_v1__": "Настройки документа",
    "fps": "Частота кадров",
    "encoding": "Кодировка",
    "bom": "Метка кодировки",
    "app_version": "Версия редактора",
    "newline": "Переносы строк",
    "trailing_newline": "Завершающий перенос",
    "warnings": "Замечания документа",
    "review_settings": "Настройки проверки",
}


def display(value):
    if value is _MISSING:
        return "Удалено / отсутствует"
    if value is None:
        return "Не задано"
    if isinstance(value, str):
        return value.replace(r"\N", "\n")
    if (
        isinstance(value, list)
        and value
        and all(isinstance(c, dict) and "id" in c and "start" in c for c in value)
    ):
        return "\n".join(
            f"{i + 1}. [{c['start']}–{c['end']} мс] {c.get('translation') if c.get('translation') is not None else c.get('text', '')}"
            for i, c in enumerate(value)
        )
    return json.dumps(value, ensure_ascii=False, indent=2)


def merge_documents(base, mine, server, choices=None):
    """Return candidate, conflicts and all changed fields. Unchosen conflicts
    use server values only as a preview; callers must reject unresolved choices.
    """
    for document in (base, mine, server):
        validate_document(document)
    if (
        base["source_lines"] != mine["source_lines"]
        or base["source_lines"] != server["source_lines"]
    ):
        raise ValueError(
            "Исходник изменился. Для этой версии нужно отдельное сопоставление исходника"
        )
    conflicts, changes = [], []
    choices = choices or {}

    def merge(a, b, c, path, title):
        if a == b == c:
            return deepcopy(c) if c is not _MISSING else _MISSING
        key = json.dumps(path, ensure_ascii=False, separators=(",", ":"))
        if all(isinstance(v, dict) for v in (a, b, c)):
            result = {}
            for field in sorted(a.keys() | b.keys() | c.keys()):
                value = merge(
                    a.get(field, _MISSING),
                    b.get(field, _MISSING),
                    c.get(field, _MISSING),
                    [*path, field],
                    title + " · " + LABELS.get(field, field),
                )
                if value is not _MISSING:
                    result[field] = value
            return result
        row = {
            "key": key,
            "path": path,
            "title": title,
            "base": display(a),
            "mine": display(b),
            "server": display(c),
            "mineChanged": a != b,
            "serverChanged": a != c,
        }
        changes.append(row)
        if a == b:
            value = c
        elif a == c or b == c:
            value = b
        else:
            conflicts.append(row)
            value = b if choices.get(key) == "mine" else c
        return deepcopy(value) if value is not _MISSING else _MISSING

    result = deepcopy(server)
    for field in sorted(base.keys() | mine.keys() | server.keys()):
        if field in ("source_lines", "cues", "schema_version"):
            continue
        value = merge(
            base.get(field, _MISSING),
            mine.get(field, _MISSING),
            server.get(field, _MISSING),
            [field],
            LABELS.get(field, field),
        )
        if value is _MISSING:
            result.pop(field, None)
        else:
            result[field] = value
    lists = [d["cues"] for d in (base, mine, server)]
    ids = [[c["id"] for c in cues] for cues in lists]
    if ids[0] == ids[1] == ids[2]:
        result["cues"] = [
            merge(a, b, c, ["cues", a["id"]], f"Реплика {i + 1}")
            for i, (a, b, c) in enumerate(zip(*lists))
        ]
    else:
        result["cues"] = merge(
            *lists,
            ["cues"],
            "Состав и порядок реплик (разделение, объединение, удаление)",
        )
    # Server source/original invariants still apply after a deliberate choice.
    old = {c["id"]: c for c in server["cues"]}
    if any(
        c["id"] in old and c.get("original") != old[c["id"]].get("original")
        for c in result["cues"]
    ):
        raise ValueError("Согласование не может изменять оригинал существующей реплики")
    try:
        validate_document(result)
    except ValueError:
        # Separately valid edits can form an invalid interval or remove the last
        # playable cue. Require a whole cue-sequence choice in that case.
        conflicts[:] = [r for r in conflicts if r["path"][0] != "cues"]
        changes[:] = [r for r in changes if r["path"][0] != "cues"]
        result["cues"] = merge(
            *lists,
            ["cues"],
            "Связанные правки реплик и таймкодов: выберите одну версию",
        )
        validate_document(result)
    return result, conflicts, changes
