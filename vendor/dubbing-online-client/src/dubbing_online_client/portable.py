"""Autonomous Substance snapshots and durable, reviewed text return transfers.

Origin is a locator, never a credential or authority. The base is read from
server history, and the normal document PUT enforces permissions and CAS.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .api import ApiError, normalize_server_url
from .documents import STAMP, from_substance, to_substance, validate_document
from .merge import display, merge_documents
from .repository import RemoteDocumentRepository, atomic_json

ORIGIN = "dubbing_online_origin"
WIRE_EXTRAS = "dubbing_online_wire_extras"
MAX_FILE_BYTES = 100 * 1024 * 1024


def digest(document):
    return hashlib.sha256(
        json.dumps(
            document, sort_keys=True, ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def read_portable(path):
    path = Path(path)
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("Файл Substance превышает 100 МБ")
    snapshot = json.loads(raw.decode("utf-8-sig"))
    origin = snapshot.get(ORIGIN) if isinstance(snapshot, dict) else None
    validate_origin(origin)
    return snapshot


def validate_origin(origin):
    if (
        not isinstance(origin, dict)
        or type(origin.get("version")) is not int
        or origin["version"] != 1
        or type(origin.get("base_revision")) is not int
        or origin["base_revision"] < 1
        or not isinstance(origin.get("base_sha256"), str)
        or not re.fullmatch(r"[0-9a-f]{64}", origin["base_sha256"])
    ):
        raise ValueError(
            "Нет корректного происхождения онлайн-серии. Экспортируйте серию из онлайн-проекта"
        )
    for field in ("project_id", "episode_id"):
        if not isinstance(origin.get(field), str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}", origin[field]
        ):
            raise ValueError("Некорректное происхождение онлайн-серии")
    if not isinstance(origin.get("server_url"), str):
        raise ValueError("Некорректный адрес сервера")
    origin["server_url"] = normalize_server_url(origin["server_url"])
    return origin


def export_ass(client, project_id, episode_id, path):
    from .ass_transfer import write_ass

    reply = client.request(
        "GET", f"/v1/projects/{project_id}/episodes/{episode_id}/document"
    )
    if (
        reply.get("project_id") != project_id
        or reply.get("episode_id") != episode_id
        or type(reply.get("revision")) is not int
        or reply["revision"] < 1
    ):
        raise ValueError("В серии ещё нет текста")
    glossary = client.request("GET", f"/v1/projects/{project_id}/glossary")
    names = {
        row["id"]: row["data"]["name"]
        for row in glossary
        if row["kind"] == "character"
    }
    origin = {
        "version": 1,
        "server_url": normalize_server_url(client.url),
        "project_id": project_id,
        "episode_id": episode_id,
        "base_revision": reply["revision"],
        "source_version": reply.get("source_version", 1),
        "base_sha256": digest(reply["document"]),
    }
    write_ass(path, reply["document"], origin, names)


def export_snapshot(client, project_id, episode_id):
    path = f"/v1/projects/{project_id}/episodes/{episode_id}"
    reply = client.request("GET", path + "/document")
    if (
        reply.get("project_id") != project_id
        or reply.get("episode_id") != episode_id
        or type(reply.get("revision")) is not int
        or reply["revision"] < 1
    ):
        raise ValueError("В серии ещё нет текста")
    snapshot = to_substance(reply["document"])
    glossary = client.request("GET", f"/v1/projects/{project_id}/glossary")
    snapshot["characters"], snapshot["terms"], snapshot["images"] = [], [], {}
    for entry in glossary:
        record = {**deepcopy(entry["data"]), "id": entry["id"]}
        if entry["kind"] == "character":
            record["primary"] = record.get("primary") or ""
            snapshot["characters"].append(record)
            for portrait in record.get("portraits", []):
                for field in ("source", "image"):
                    asset = portrait[field]
                    if asset not in snapshot["images"]:
                        snapshot["images"][asset] = client.image(project_id, asset)
        else:
            snapshot["terms"].append(record)
    names = {c["id"]: c["name"] for c in snapshot["characters"]}
    for cue, wire_cue in zip(snapshot["cues"], reply["document"]["cues"]):
        cue["character"] = names.get(cue["character_id"], "")
        cue.setdefault("extras", {})[WIRE_EXTRAS] = {
            key: deepcopy(value)
            for key, value in wire_cue.get("extras", {}).items()
            if key != STAMP
        }
    threads, after = [], ""
    while True:
        page = client.request("GET", path + "/reviews", query={"after": after})
        threads.extend(page["items"])
        following = page.get("next")
        if not following:
            break
        if (
            not isinstance(following, str)
            or following <= after
            or len(threads) > 100_000
        ):
            raise ApiError("invalid_response")
        after = following
    # Keep shared context in origin, including full reply history. Local remarks
    # are independent records; returning a file never mutates shared discussions.
    local_reviews = deepcopy(snapshot.get("reviews", []))
    for thread in threads:
        if thread.get("has_older_messages"):
            messages, cursor = [], 1
            while True:
                page = client.request(
                    "GET",
                    path + "/reviews/" + thread["id"] + "/messages",
                    query={"after": cursor},
                )
                older = page["items"]
                messages.extend(older)
                following = page.get("next")
                if not following:
                    break
                if (
                    type(following) is not int
                    or following <= cursor
                    or len(messages) > 100_000
                ):
                    raise ApiError("invalid_response")
                cursor = following
            thread["messages"] = messages
        if thread.get("archived_source"):
            continue
        local_reviews.append(
            {
                "id": "online_" + thread["id"],
                "kind": "note",
                "cue_ids": [thread["cue_id"]],
                "text": thread["author_name"]
                + ": "
                + thread["text"]
                + (
                    "\nПредложение: " + thread["replacement"]
                    if thread.get("replacement") is not None
                    else ""
                )
                + "".join(
                    "\n" + m["author_name"] + ": " + m["text"]
                    for m in thread["messages"]
                ),
                "state": "open" if thread["state"] == "open" else "resolved",
                "created": thread["created_at"],
                "updated": thread["created_at"],
                "extras": {
                    "online_thread_id": thread["id"],
                    "online_version": thread["version"],
                },
            }
        )
    snapshot["reviews"] = local_reviews
    snapshot[ORIGIN] = {
        "version": 1,
        "server_url": normalize_server_url(client.url),
        "project_id": project_id,
        "episode_id": episode_id,
        "base_revision": reply["revision"],
        "source_version": reply.get("source_version", 1),
        "base_sha256": digest(reply["document"]),
        "document_extras": {
            key: deepcopy(value)
            for key, value in reply["document"].get("extras", {}).items()
            if key != STAMP
        },
        "glossary_revisions": {row["id"]: row["revision"] for row in glossary},
        "reviews": threads,
    }
    # Adapters remove media and ASS media headers. Validate before writing any file.
    from_substance(snapshot)
    return snapshot


def write_portable(path, snapshot):
    if Path(path).suffix.lower() != ".substance":
        raise ValueError("Выберите файл с расширением .substance")
    if (
        len(json.dumps(snapshot, ensure_ascii=False, allow_nan=False).encode())
        > MAX_FILE_BYTES
    ):
        raise ValueError("Переносимый файл превышает 100 МБ")
    atomic_json(path, snapshot)


def returned_document(snapshot, base):
    """Restore opaque server fields and exact immutable sources after local IO.

    Only text/document changes return here. Glossary and discussions have their own
    revision contracts; an older file must never replace those project collections.
    """
    expected = to_substance(base)
    if snapshot.get("source_lines") != expected["source_lines"]:
        raise ValueError("Исходник файла изменён. Нужна отдельная замена исходника")
    clean = deepcopy(snapshot)
    for key in (ORIGIN, "reviews", "terms"):
        clean.pop(key, None)
    opaque = {}
    for cue in clean.get("cues", []):
        value = cue.get("extras", {}).pop(WIRE_EXTRAS, {})
        if not isinstance(value, dict) or STAMP in value:
            raise ValueError("Некорректные дополнительные данные реплики")
        opaque[cue["id"]] = value
    wire, _, _ = from_substance(clean)
    wire["source_lines"] = deepcopy(base["source_lines"])
    # Opening a local file updates these IO diagnostics in Substance. They are
    # not a change to the episode's source provenance or a path to publish.
    for key in ("source_path", "source_format", "source_sha256"):
        if key in base.get("metadata", {}):
            wire["metadata"][key] = deepcopy(base["metadata"][key])
        else:
            wire["metadata"].pop(key, None)
    old = {c["id"]: c for c in base["cues"]}
    for cue in wire["cues"]:
        previous = old.get(cue["id"], {})
        if previous and cue["original"] != previous["original"]:
            raise ValueError("Оригинал существующей реплики изменён")
        if not previous:
            originals = {
                c["original"]
                for c in base["cues"]
                if c["source_ids"] == cue["source_ids"]
            }
            originals.add(
                r"\N".join(
                    base["source_lines"][sid]["text"] for sid in cue["source_ids"]
                )
            )
            if cue["original"] not in originals:
                raise ValueError("Новый ID реплики не разрешает замену исходника")
        details = deepcopy(previous.get("extras", {}))
        details.update(opaque[cue["id"]])
        details[STAMP] = {**deepcopy(details.get(STAMP, {})), **cue["extras"][STAMP]}
        previous_details = previous.get("extras", {}).get(STAMP, {})
        for key, default in {"baseline": {}, "original_line": "", "extras": {}}.items():
            if key not in previous_details and details[STAMP].get(key) == default:
                details[STAMP].pop(key, None)
        if previous and previous.get("character_id") == cue.get("character_id"):
            if "character" in previous_details:
                details[STAMP]["character"] = deepcopy(previous_details["character"])
            else:
                details[STAMP].pop("character", None)
        cue["extras"] = details
    details = deepcopy(base.get("extras", {}))
    details[STAMP] = {**deepcopy(details.get(STAMP, {})), **wire["extras"][STAMP]}
    details[STAMP].pop(ORIGIN, None)
    previous_details = base.get("extras", {}).get(STAMP, {})
    # Merely opening/saving in another editor version is not an authored change.
    if "app_version" in previous_details:
        details[STAMP]["app_version"] = deepcopy(previous_details["app_version"])
    else:
        details[STAMP].pop("app_version", None)
    for key, default in {
        "fps": 23.976,
        "bom": False,
        "encoding": "utf-8",
        "newline": "\n",
        "trailing_newline": True,
        "warnings": [],
        "review_settings": {},
    }.items():
        if key not in previous_details and details[STAMP].get(key) == default:
            details[STAMP].pop(key, None)
    # Local read-only copies of server discussions and the project glossary
    # never become a replacement for the server's own records.
    for key in ("reviews", "terms"):
        if key in base.get("extras", {}).get(STAMP, {}):
            details[STAMP][key] = deepcopy(base["extras"][STAMP][key])
        else:
            details[STAMP].pop(key, None)
    wire["extras"] = details
    validate_document(wire)
    return wire


class PortableTransfer(RemoteDocumentRepository):
    """One recoverable return transfer per server/account/project/episode."""

    def prepare(self, snapshot, filename):
        reply = self._transfer_base(validate_origin(snapshot[ORIGIN]))
        mine = returned_document(snapshot, reply["document"])
        return self._prepare(reply, mine, filename)

    def _transfer_base(self, origin):
        if self._state and (self.pending or self._state.get("transfer")):
            raise ValueError("Сначала завершите или отмените сохранённую загрузку")
        if [origin["server_url"], origin["project_id"], origin["episode_id"]] != [
            normalize_server_url(self.client.url),
            self.context[2],
            self.context[3],
        ]:
            raise ValueError("Файл принадлежит другому серверу, проекту или серии")
        reply = self.client.request(
            "GET", self.base + "/revisions/" + str(origin["base_revision"])
        )
        self._validate_reply(reply)
        if (
            reply["revision"] != origin["base_revision"]
            or digest(reply["document"]) != origin["base_sha256"]
        ):
            raise ValueError("Базовая версия файла не совпадает с серверной историей")
        return reply

    def _prepare(self, reply, mine, filename, **extra):
        remote = self.client.request("GET", self.base + "/document")
        self._validate_reply(remote)
        merge_documents(reply["document"], mine, remote["document"])
        self._persist(
            {
                "version": 1,
                "context": self.context,
                "revision": reply["revision"],
                "confirmed": reply["document"],
                "draft": mine,
                "pending": None,
                "remote": remote,
                "transfer": Path(filename).name,
                **extra,
            }
        )
        self.remote = deepcopy(remote)
        return self.preview()

    def prepare_ass(self, imported, filename, base_revision=0):
        from .ass_transfer import MAPPING_VERSION, automatic_mapping, mapped_document

        origin = imported.get("origin")
        if origin is not None:
            reply = self._transfer_base(validate_origin(origin))
        else:
            if type(base_revision) is not int or base_revision < 1:
                raise ValueError(
                    "ASS без происхождения: укажите номер серверной версии, которую редактировали"
                )
            # Without embedded provenance the human chooses the base explicitly.
            if self._state and (self.pending or self._state.get("transfer")):
                raise ValueError("Сначала завершите или отмените сохранённую загрузку")
            reply = self.client.request(
                "GET", self.base + "/revisions/" + str(base_revision)
            )
            self._validate_reply(reply)
            if reply["revision"] != base_revision:
                raise ValueError("Базовая версия ASS не совпадает с серверной историей")
        mapping = automatic_mapping(reply["document"], imported)
        return self._prepare(
            reply,
            mapped_document(reply["document"], imported, mapping, partial=True),
            filename,
            ass={
                "imported": imported,
                "mapping": mapping,
                "automatic_mapping_done": True,
                "automatic_mapping_version": MAPPING_VERSION,
                "base": reply["document"],
                "locked": False,
            },
        )

    def map_ass(self, row, target):
        from .ass_transfer import mapped_document

        if (
            not self._state
            or not self._state.get("transfer")
            or not self._state.get("ass")
        ):
            raise ValueError("Нет ASS для сопоставления")
        state = deepcopy(self._state)
        details = state["ass"]
        if details["locked"] or state.get("pending"):
            raise ValueError("Отправленное сопоставление нельзя менять")
        if row not in {str(i) for i in range(len(details["imported"]["rows"]))}:
            raise ValueError("Неизвестная строка ASS")
        ids = {c["id"] for c in details["base"]["cues"]}
        if target not in ids | {"", "skip"}:
            raise ValueError("Неизвестная реплика")
        if target not in ("", "skip") and any(
            k != row and v == target for k, v in details["mapping"].items()
        ):
            raise ValueError(
                "Реплика уже выбрана: split/merge требует отдельной проверки"
            )
        if target:
            details["mapping"][row] = target
        else:
            details["mapping"].pop(row, None)
        if row not in details.setdefault("manual_rows", []):
            details["manual_rows"].append(row)
        state["draft"] = mapped_document(
            details["base"], details["imported"], details["mapping"], partial=True
        )
        self._persist(state)
        return self.preview()

    def preview(self):
        from .ass_transfer import output_text

        if not self._state or not self._state.get("transfer"):
            return {}
        server = self.remote or {
            "revision": self.revision,
            "document": self._state["confirmed"],
        }
        retry = bool(self._state["pending"] and not self._state.get("pending_rejected"))
        try:
            _, conflicts, changes = merge_documents(
                self._state["confirmed"], self.snapshot, server["document"]
            )
            error = ""
        except ValueError as exc:
            conflicts, changes, error = [], [], str(exc)
        conflict_keys = {row["key"] for row in conflicts}
        changes.sort(key=lambda row: row["key"] not in conflict_keys)
        result = {
            "token": self._comparison_token(),
            "filename": self._state["transfer"],
            "base_revision": self.revision,
            "server_revision": server["revision"],
            "conflicts": conflicts,
            "changes": changes,
            "retry": retry,
            "error": error,
        }
        # Internal ASS cache invalidation is not an extra user edit. Retain any
        # conflict, even on these fields, so the publish contract stays explicit.
        visible_changes = [
            dict(r) for r in changes
            if r["key"] in conflict_keys or not (
                len(r["path"]) >= 5
                and r["path"][0] == "cues"
                and r["path"][2:4] == ["extras", STAMP]
                and r["path"][4] in ("original_line", "field_order")
            )
        ]
        file_changes = [r for r in visible_changes if r["mineChanged"]]
        changed_ids = {
            r["path"][1] for r in file_changes
            if r["path"][0] == "cues" and len(r["path"]) > 1
        }
        cue_by_id = {c["id"]: c for c in self._state["confirmed"]["cues"]}
        document_cues = [
            {c["id"]: c for c in document["cues"]}
            for document in (self._state["confirmed"], self.snapshot, server["document"])
        ]
        for row in visible_changes:
            path = row["path"]
            cue = (
                cue_by_id.get(path[1])
                if len(path) > 1 and path[0] == "cues" else None
            )
            row["context"] = (
                f"{self._time(cue['start'])} – {self._time(cue['end'])}"
                if cue else "Документ"
            )
            row["conflict"] = row["key"] in conflict_keys
            if len(path) == 3 and path[0] == "cues" and path[2] in ("translation", "start", "end"):
                for field, cues in zip(("base", "mine", "server"), document_cues):
                    value = cues[path[1]]
                    row[field] = (
                        display(output_text(value)) if path[2] == "translation"
                        else self._time(value[path[2]])
                    )
        result.update(
            review_changes=visible_changes,
            changed_cues=len(changed_ids),
            file_fields=len(file_changes),
            server_fields=sum(
                r["serverChanged"] and not r["mineChanged"] for r in visible_changes
            ),
        )
        details = self._state.get("ass")
        if details:
            def label(c, i, text):
                return f"{i + 1}. {self._time(c['start'])} – {self._time(c['end'])} · {text}"

            targets = [
                {
                    "id": c["id"],
                    "label": label(c, i, c["original"] + " → " + output_text(c)),
                }
                for i, c in enumerate(details["base"]["cues"])
            ]
            result.update(
                ass=True,
                mapping=details["mapping"],
                mapping_locked=details["locked"],
                mapping_complete=len(details["mapping"])
                == len(details["imported"]["rows"]),
                unresolved_rows=len(details["imported"]["rows"]) - len(details["mapping"]),
                unchanged_cues=len(details["base"]["cues"]) - len(changed_ids),
                mapping_rows=[
                    {
                        "key": str(i),
                        "label": label(c, i, c["text"]),
                        "name": c["ass_fields"].get(
                            "Name", c["ass_fields"].get("Actor", "")
                        ),
                    }
                    for i, c in enumerate(details["imported"]["rows"])
                ],
                mapping_targets=targets,
                preserved_rows=len(targets)
                - len({v for v in details["mapping"].values() if v != "skip"}),
            )
            result["token"] = digest(
                {"comparison": result["token"], "mapping": details["mapping"]}
            )
        return result

    @staticmethod
    def _time(ms):
        return f"{ms // 60000:02}:{ms // 1000 % 60:02}.{ms % 1000 // 10:02}"

    def refresh(self):
        from .ass_transfer import MAPPING_VERSION, automatic_mapping, mapped_document

        if self._state and self._state.get("transfer"):
            details = self._state.get("ass")
            if (
                details and details.get("automatic_mapping_version", 0) < MAPPING_VERSION
                and not details["locked"] and not self.pending
            ):
                state = deepcopy(self._state)
                details = state["ass"]
                used = set(details["mapping"].values())
                matches = automatic_mapping(details["base"], details["imported"])
                for row, target in matches.items():
                    if (
                        row not in details["mapping"] and target not in used
                        and row not in details.get("manual_rows", [])
                    ):
                        details["mapping"][row] = target
                        used.add(target)
                details["automatic_mapping_done"] = True
                details["automatic_mapping_version"] = MAPPING_VERSION
                state["draft"] = mapped_document(
                    details["base"], details["imported"], details["mapping"], partial=True
                )
                self._persist(state)
            # A prepared no-op still needs to retain its file/base for comparison.
            reply = self.client.request("GET", self.base + "/document")
            self._remember_remote(reply)
        return self.preview()

    def publish(self, token, choices):
        preview = self.preview()
        if not preview or preview["token"] != token:
            raise ValueError("Сравнение изменилось. Обновите его перед загрузкой")
        if not preview["retry"]:
            if preview.get("ass") and not preview["mapping_complete"]:
                raise ValueError("Сопоставьте или пропустите каждую строку ASS")
            if preview["error"]:
                raise ValueError(preview["error"])
            if any(
                choices.get(c["key"]) not in ("mine", "server")
                for c in preview["conflicts"]
            ):
                raise ValueError("Выберите значение каждого конфликтующего поля")
            server = self.remote or {
                "revision": self.revision,
                "document": self._state["confirmed"],
            }
            candidate, _, _ = merge_documents(
                self._state["confirmed"], self.snapshot, server["document"], choices
            )
            from uuid import uuid4

            recovery = self.path.with_name("recovery-" + uuid4().hex + ".json")
            atomic_json(recovery, self._state)
            state = deepcopy(self._state)
            if state.get("ass"):
                state["ass"]["locked"] = True
            state.update(
                revision=server["revision"],
                confirmed=server["document"],
                draft=candidate,
                pending=None,
                pending_rejected=False,
                remote=None,
            )
            self._persist(state)
            self.remote = None
        try:
            self.sync()
            state = deepcopy(self._state)
            state["transfer"] = ""
            self._persist(state)
            return self.revision
        except ApiError as exc:
            # These are definitive pre-write rejections, unlike timeouts/5xx.
            if self._state["pending"] and exc.status in (400, 401, 403, 404, 409, 422):
                state = deepcopy(self._state)
                state["pending_rejected"] = True
                self._persist(state)
            raise

    def discard(self):
        if (
            self._state
            and self._state["pending"]
            and not self._state.get("pending_rejected")
        ):
            raise ValueError(
                "Результат отправки неизвестен. Сначала повторите отправку"
            )
        if self._state:
            from uuid import uuid4

            atomic_json(
                self.path.with_name("recovery-" + uuid4().hex + ".json"), self._state
            )
            state = deepcopy(self._state)
            state.update(
                draft=state["confirmed"],
                pending=None,
                pending_rejected=False,
                remote=None,
                transfer="",
            )
            self._persist(state)
            self.remote = None
