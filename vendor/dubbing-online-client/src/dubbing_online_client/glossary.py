"""Independent glossary cache and durable form/outbox; never part of episode Undo."""

from copy import deepcopy
import base64
import hashlib
import json
import re
import threading
from uuid import UUID, uuid4

from .api import ApiError
from .repository import atomic_json


class RemoteGlossary:
    def __init__(self, repository):
        self.repository = repository
        self.path = repository.path.with_name("glossary.json")
        self.base = f"/v1/projects/{repository.context[2]}/glossary"
        self._lock = threading.RLock()
        self.state = {
            "version": 1,
            "context": repository.context,
            "draft": {},
            "pending": None,
            "rejected": False,
            "items": [],
        }
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("version") != 1 or state.get("context") != repository.context:
                raise ValueError("Некорректный журнал глоссария")
            if not isinstance(state.get("draft"), dict) or not isinstance(
                state.get("items"), list
            ):
                raise ValueError("Некорректный черновик глоссария")
            if state.get("pending"):
                UUID(state["pending"]["body"]["operation_id"])
                self._target(state["pending"])
            self.state = state

    def _persist(self, state):
        atomic_json(self.path, state)
        self.state = state

    @property
    def items(self):
        with self._lock:
            return deepcopy(self.state["items"])

    @property
    def pending(self):
        return bool(self.state["pending"])

    def save_draft(self, draft):
        with self._lock:
            state = deepcopy(self.state)
            state["draft"] = deepcopy(draft)
            self._persist(state)

    def enqueue(self, proposal=False, *, draft=None):
        """Queue an independent portrait change without replacing an open form."""
        with self._lock:
            if self.pending:
                raise ValueError("Сначала подтвердите сохранённую операцию глоссария")
            independent = draft is not None
            draft = deepcopy(draft) if independent else self.state["draft"]
            if not draft.get("data", {}).get("name", "").strip():
                raise ValueError("Укажите имя карточки или термина")
            operation = {
                "action": "propose"
                if proposal
                else "update"
                if draft.get("id")
                else "create",
                "id": draft.get("id", ""),
                "base_data": deepcopy(draft.get("base_data", {})),
                "body": {"operation_id": str(uuid4()), "data": deepcopy(draft["data"])},
            }
            images = deepcopy(draft.get("images", {}))
            for asset, encoded in images.items():
                raw = base64.b64decode(encoded, validate=True)
                if (len(raw) > 6 * 1024 * 1024
                        or asset != "img_" + hashlib.sha256(raw).hexdigest()
                        or not raw.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))):
                    raise ValueError("Некорректное изображение портрета")
            if images:
                operation["images"] = images
            if operation["action"] == "create":
                operation["body"]["kind"] = draft["kind"]
            else:
                operation["body"]["base_revision"] = draft["base_revision"]
            self._target(operation)
            state = deepcopy(self.state)
            state.update(pending=operation, rejected=False)
            if not independent:
                state["draft"] = {}
            self._persist(state)  # a failed disk write prevents sending

    def _target(self, operation):
        action, entry_id = operation["action"], operation["id"]
        if action == "create" and not entry_id:
            return "POST", self.base
        if action not in ("update", "propose") or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,100}", entry_id
        ):
            raise ValueError("Некорректная операция глоссария")
        return (
            ("PUT", self.base + "/" + entry_id)
            if action == "update"
            else ("POST", self.base + "/" + entry_id + "/proposals")
        )

    def sync(self):
        with self._lock:
            operation = deepcopy(self.state["pending"])
            rejected = self.state["rejected"]
        if operation and not rejected:
            method, path = self._target(operation)
            try:
                # Content-addressed uploads are safe to repeat after a timeout.
                # Keep bytes with the durable operation until its acknowledgement.
                if operation.get("images") and not operation.get("images_uploaded"):
                    assets = {}
                    for asset, encoded in operation["images"].items():
                        result = self.repository.client.request(
                            "POST", self.base.removesuffix("/glossary") + "/assets/images",
                            base64.b64decode(encoded, validate=True), binary=True,
                        )
                        if not isinstance(result, dict) or not re.fullmatch(
                            r"img_[0-9a-f]{64}", result.get("id", "")
                        ):
                            raise ApiError("invalid_response")
                        assets[asset] = result["id"]
                    # The server strips metadata and re-encodes images. Its IDs
                    # can differ from the local bytes. Persist the final payload
                    # before the first card write, then retry it unchanged.
                    for portrait in operation["body"]["data"].get("portraits", []):
                        for key in ("source", "image"):
                            portrait[key] = assets.get(portrait[key], portrait[key])
                    operation["images_uploaded"] = True
                    with self._lock:
                        state = deepcopy(self.state)
                        state["pending"] = deepcopy(operation)
                        self._persist(state)
                self.repository.client.request(method, path, operation["body"])
            except ApiError as exc:
                # Only explicit rejection permits editing/cancelling. A timeout
                # may already have committed and must retry the same identity.
                if exc.status in (400, 401, 403, 404, 409, 422):
                    with self._lock:
                        state = deepcopy(self.state)
                        state["rejected"] = True
                        self._persist(state)
                raise
            with self._lock:
                state = deepcopy(self.state)
                state.update(pending=None, rejected=False)
                self._persist(state)
        self.refresh()

    def refresh(self):
        items = self.repository.client.request("GET", self.base)
        if not isinstance(items, list) or any(
            not isinstance(row, dict)
            or row.get("kind") not in ("character", "term")
            or not isinstance(row.get("data"), dict)
            or type(row.get("revision")) is not int
            or row["revision"] < 1
            for row in items
        ):
            raise ApiError("invalid_response")
        with self._lock:
            state = deepcopy(self.state)
            state["items"] = items
            self._persist(state)

    def restore_pending(self):
        with self._lock:
            if not self.pending or not self.state["rejected"]:
                raise ValueError(
                    "Результат отправки неизвестен. Сначала повторите операцию"
                )
            if self.state["draft"]:
                raise ValueError("Другой черновик уже открыт")
            op = self.state["pending"]
            state = deepcopy(self.state)
            state["draft"] = {
                "id": op["id"],
                "kind": op["body"].get("kind", ""),
                "base_revision": op["body"].get("base_revision", 0),
                "data": deepcopy(op["body"]["data"]),
            }
            if op["id"]:
                row = next((r for r in self.items if r["id"] == op["id"]), None)
                if row:
                    state["draft"]["kind"] = row["kind"]
            # Keep the original base from the form for explicit conflict comparison.
            state["draft"]["base_data"] = deepcopy(op.get("base_data", {}))
            if op.get("images"):
                state["draft"]["images"] = deepcopy(op["images"])
            state.update(pending=None, rejected=False)
            self._persist(state)

    def retry(self):
        with self._lock:
            state = deepcopy(self.state)
            state["rejected"] = False
            self._persist(state)

    def rebase(self, choices):
        """Use latest cached server base only after every conflict has a choice."""
        with self._lock:
            draft = deepcopy(self.state["draft"])
            row = next((r for r in self.items if r["id"] == draft.get("id")), None)
            if not row:
                raise ValueError("Карточка недоступна")
            base, mine, current = draft.get("base_data", {}), draft["data"], row["data"]
            merged = deepcopy(current)
            for key, value in mine.items():
                if value == base.get(key):
                    continue
                if current.get(key) != base.get(key) and current.get(key) != value:
                    if choices.get(key) not in ("mine", "server"):
                        raise ValueError(
                            "Выберите значение каждого конфликтующего поля"
                        )
                    if choices[key] == "server":
                        continue
                merged[key] = deepcopy(value)
            draft.update(
                base_revision=row["revision"], base_data=deepcopy(current), data=merged
            )
            state = deepcopy(self.state)
            state["draft"] = draft
            self._persist(state)
