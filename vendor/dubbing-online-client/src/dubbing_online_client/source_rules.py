"""Pure, shared source replacement rules. The server repeats every decision check."""

from copy import deepcopy


def replacement_document(current, candidate, rows, discard_unmapped):
    old = {c["id"]: c for c in current["cues"]}
    new = {c["id"]: c for c in candidate["cues"]}
    if not new or set(rows) != set(new):
        raise ValueError("Сопоставьте каждую новую строку, включая новые реплики")
    if set(old).intersection(new) or set(current["source_lines"]).intersection(
        candidate["source_lines"]
    ):
        raise ValueError("Новая версия исходника должна иметь собственные ID")
    used = []
    result = deepcopy(candidate)
    for cue in result["cues"]:
        choice = rows[cue["id"]]
        previous = choice["old_cue_id"]
        if previous is not None:
            if previous not in old or previous in used:
                raise ValueError("Старая реплика отсутствует или сопоставлена повторно")
            if old[previous]["comment"] != cue["comment"]:
                raise ValueError("Комментарий нельзя сопоставить с репликой")
            used.append(previous)
        if choice["translation"] == "carry":
            if previous is None:
                raise ValueError("Для переноса перевода нужна старая реплика")
            source = old[previous]
            cue["translation"] = (
                source["translation"]
                if source["translation"] is not None
                else source["text"]
            )
        elif choice["translation"] == "discard":
            cue["translation"] = ""
        else:
            raise ValueError("Явно выберите перенос или очистку перевода")
        # Working text in the source file is never an implicit translation.
        cue["text"] = cue["original"]
    removed = set(old) - set(used)
    if removed and not discard_unmapped:
        raise ValueError(
            "Подтвердите, что перевод несопоставленных строк не переносится"
        )
    return result
