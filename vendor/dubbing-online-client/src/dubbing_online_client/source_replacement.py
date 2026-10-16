"""Recoverable, explicit administrative replacement, separate from return transfers."""

from copy import deepcopy
from pathlib import Path
from uuid import uuid4

from .source_rules import replacement_document
from .api import ApiError
from .documents import STAMP, validate_document
from .portable import digest
from .repository import RemoteDocumentRepository, atomic_json


def new_source(document):
    """Allocate a new source generation; never inherit a file's working/review layer."""
    validate_document(document)
    document = deepcopy(document)
    for cue in document["cues"]:
        for key, default in dict(
            text="",
            original="",
            translation=None,
            character_id=None,
            comment=False,
            ass_fields={},
            extras={},
        ).items():
            cue.setdefault(key, deepcopy(default))
    source_ids = {sid: "src_" + uuid4().hex for sid in document["source_lines"]}
    document["source_lines"] = {
        source_ids[sid]: {**line, "id": source_ids[sid]}
        for sid, line in document["source_lines"].items()
    }
    for cue in document["cues"]:
        cue.update(
            id="cue_" + uuid4().hex,
            source_ids=[source_ids[s] for s in cue["source_ids"]],
            text=cue["original"],
            translation="",
        )
    details = document.get("extras", {}).get(STAMP, {})
    for key in ("reviews", "terms", "dubbing_online_origin"):
        details.pop(key, None)
    return document


class SourceReplacement(RemoteDocumentRepository):
    def _save(self, details):
        state = deepcopy(self._state)
        state["replacement"] = details
        self._persist(state)
        return self.preview()

    def _context(self):
        reply = self.client.request("GET", self.base + "/source-replacements/context")
        self._validate_reply(reply)
        if (
            type(reply.get("source_version")) is not int
            or reply["source_version"] < 1
            or not isinstance(reply.get("reviews"), list)
        ):
            raise ApiError("invalid_response")
        return reply

    def prepare(self, document, filename):
        if self._state and self._state.get("replacement"):
            raise ValueError("Сначала завершите или отмените сохранённую замену")
        context = self._context()
        candidate = new_source(document)
        validate_document(candidate)
        self._persist(
            dict(
                version=1,
                context=self.context,
                revision=context["revision"],
                confirmed=context["document"],
                draft=context["document"],
                pending=None,
                replacement=dict(
                    candidate=candidate,
                    filename=Path(filename).name,
                    context=context,
                    rows={},
                    reviews={},
                    reason="",
                    discard_unmapped=False,
                ),
            )
        )
        return self.preview()

    def _editable(self):
        if (
            not self._state
            or not self._state.get("replacement")
            or self._state.get("pending")
        ):
            raise ValueError(
                "Отправленную замену нельзя менять. Сначала получите результат или обновите сравнение"
            )
        return deepcopy(self._state["replacement"])

    def map_row(self, cue_id, old_cue_id, translation, character_id):
        details = self._editable()
        cue = next((c for c in details["candidate"]["cues"] if c["id"] == cue_id), None)
        if cue is None or translation not in ("carry", "discard"):
            raise ValueError("Неизвестная строка или решение о переводе")
        if old_cue_id and old_cue_id not in {
            c["id"] for c in details["context"]["document"]["cues"]
        }:
            raise ValueError("Неизвестная старая реплика")
        if old_cue_id and any(
            key != cue_id and c["old_cue_id"] == old_cue_id
            for key, c in details["rows"].items()
        ):
            raise ValueError(
                "Старая строка уже сопоставлена. Для split/merge выберите новые строки и перенос только на одну из них"
            )
        if not old_cue_id and translation == "carry":
            raise ValueError("Новой строке нельзя перенести перевод без старой реплики")
        details["rows"][cue_id] = dict(
            old_cue_id=old_cue_id or None, translation=translation
        )
        cue["character_id"] = character_id or None
        return self._save(details)

    def map_review(self, thread_id, cue_id):
        details = self._editable()
        thread = next(
            (t for t in details["context"]["reviews"] if t["id"] == thread_id), None
        )
        if thread is None or (
            cue_id and cue_id not in {c["id"] for c in details["candidate"]["cues"]}
        ):
            raise ValueError("Неизвестное замечание или новая реплика")
        details["reviews"][thread_id] = dict(
            base_version=thread["version"], cue_id=cue_id or None
        )
        return self._save(details)

    def configure(self, reason, discard_unmapped):
        details = self._editable()
        details.update(
            reason=reason,
            discard_unmapped=discard_unmapped,
        )
        return self._save(details)

    def _body(self, details):
        context = details["context"]
        body = dict(
            version=1,
            operation_id=str(uuid4()),
            base_revision=context["revision"],
            base_source_version=context["source_version"],
            reason=details["reason"],
            document=details["candidate"],
            rows=details["rows"],
            reviews=details["reviews"],
            discard_unmapped=details["discard_unmapped"],
        )
        if set(body["reviews"]) != {t["id"] for t in context["reviews"]}:
            raise ValueError(
                "Выберите перенос или сохранение в истории для каждого замечания"
            )
        if (
            not isinstance(body["reason"], str)
            or not body["reason"].strip()
            or len(body["reason"]) > 5000
        ):
            raise ValueError("Укажите причину замены длиной до 5000 символов")
        replacement_document(
            context["document"],
            body["document"],
            body["rows"],
            body["discard_unmapped"],
        )
        return body

    def preview(self):
        if not self._state or not self._state.get("replacement"):
            return {}
        details = deepcopy(self._state["replacement"])
        context = details["context"]
        old = {c["id"]: c for c in context["document"]["cues"]}
        used = {c["old_cue_id"] for c in details["rows"].values()}
        rows = []
        for i, cue in enumerate(details["candidate"]["cues"]):
            decision = details["rows"].get(cue["id"])
            previous = old.get(decision["old_cue_id"]) if decision else None
            rows.append(
                dict(
                    id=cue["id"],
                    label=f"{i + 1}. {cue['original']}",
                    original=cue["original"],
                    start=cue["start"],
                    end=cue["end"],
                    character_id=cue["character_id"],
                    comment=cue["comment"],
                    decision=decision or {},
                    previous=previous or {},
                    change="new"
                    if decision and not previous
                    else "unchanged"
                    if previous
                    and all(
                        previous[k] == cue[k]
                        for k in ("original", "start", "end", "comment")
                    )
                    else "changed"
                    if previous
                    else "unmapped",
                )
            )
        error = ""
        try:
            self._body(details)
        except ValueError as exc:
            error = str(exc)
        retry = bool(
            self._state.get("pending") and not self._state.get("pending_rejected")
        )
        result = dict(
            token=digest(self._state),
            filename=details["filename"],
            base_revision=context["revision"],
            source_version=context["source_version"],
            next_source_version=context["source_version"] + 1,
            rows=rows,
            targets=list(old.values()),
            reviews=context["reviews"],
            review_choices=details["reviews"],
            reason=details["reason"],
            discard_unmapped=details["discard_unmapped"],
            removed=[c for key, c in old.items() if key not in used],
            error=error,
            retry=retry,
            rejected=bool(self._state.get("pending_rejected")),
            can_publish=retry or (not error and not self._state.get("pending")),
        )
        return result

    def refresh(self):
        if not self._state or not self._state.get("replacement"):
            return {}
        if self._state.get("pending") and not self._state.get("pending_rejected"):
            return self.preview()  # Never reinterpret an uncertain POST.
        context = self._context()
        state = deepcopy(self._state)
        if context != state["replacement"]["context"] or state.get("pending"):
            atomic_json(self.path.with_name("recovery-" + uuid4().hex + ".json"), state)
            state.update(
                revision=context["revision"],
                confirmed=context["document"],
                draft=context["document"],
                pending=None,
                pending_rejected=False,
            )
            state["replacement"].update(
                context=context,
                rows={},
                reviews={},
                discard_unmapped=False,
            )
            self._persist(state)
        return self.preview()

    def publish(self, token, choices=None):
        preview = self.preview()
        if not preview or token != preview["token"] or not preview["can_publish"]:
            raise ValueError(
                "Проверьте сопоставление и обновите сравнение перед заменой"
            )
        if not preview["retry"]:
            state = deepcopy(self._state)
            state["pending"] = self._body(state["replacement"])
            self._persist(state)  # Must reach disk before the POST.
        body = self._state["pending"]
        try:
            result = self.client.request(
                "POST", self.base + "/source-replacements", body
            )
            if (
                result.get("operation_id") != body["operation_id"]
                or result.get("episode_id") != self.context[3]
                or result.get("project_id") != self.context[2]
                or result.get("revision") != body["base_revision"] + 1
                or result.get("source_version") != body["base_source_version"] + 1
            ):
                raise ApiError("invalid_response")
            atomic_json(
                self.path.with_name("completed-" + body["operation_id"] + ".json"),
                dict(request=body, response=result),
            )
            state = deepcopy(self._state)
            state.update(pending=None, pending_rejected=False, replacement=None)
            self._persist(state)
            return result["revision"]
        except ApiError as exc:
            if exc.status in (400, 401, 403, 404, 409, 410, 413, 422):
                state = deepcopy(self._state)
                state["pending_rejected"] = True
                self._persist(state)
            raise

    def discard(self):
        if (
            self._state
            and self._state.get("pending")
            and not self._state.get("pending_rejected")
        ):
            raise ValueError(
                "Результат отправки неизвестен. Сначала повторите отправку"
            )
        if self._state:
            atomic_json(
                self.path.with_name("recovery-" + uuid4().hex + ".json"), self._state
            )
            state = deepcopy(self._state)
            state.update(pending=None, pending_rejected=False, replacement=None)
            self._persist(state)
