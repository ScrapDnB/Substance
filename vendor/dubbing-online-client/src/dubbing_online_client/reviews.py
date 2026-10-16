"""Separate durable outbox for review discussions, owned by the episode journal lock."""

from copy import deepcopy
import json
import threading
from uuid import uuid4

from .api import ApiError
from .repository import atomic_json


class RemoteReviews:
    def __init__(self, repository):
        self.repository = repository
        self._lock = threading.RLock()
        self.path = repository.path.with_name("reviews.json")
        self.state = {
            "version": 1,
            "context": repository.context,
            "pending": None,
            "draft": {},
        }
        self.items = []
        self.permissions = {}
        if self.path.exists():
            state = json.loads(self.path.read_text(encoding="utf-8"))
            if state.get("version") != 1 or state.get("context") != repository.context:
                raise ValueError("Некорректный журнал замечаний")
            if not isinstance(state.get("draft"), dict):
                raise ValueError("Некорректный черновик замечания")
            pending = state.get("pending")
            if pending:
                if pending.get("action") not in ("create", "replies", "state"):
                    raise ValueError("Некорректная операция замечания")
                from uuid import UUID

                UUID(pending["body"]["operation_id"])
                self._path(pending)
            self.state = state

    def _persist(self, state):
        atomic_json(self.path, state)
        self.state = state

    @property
    def pending(self):
        return bool(self.state["pending"])

    def save_draft(self, draft):
        with self._lock:
            state = deepcopy(self.state)
            state["draft"] = deepcopy(draft)
            self._persist(state)

    def enqueue(self, action, body, thread_id=""):
        if self.pending:
            raise ValueError(
                "Сначала отправьте сохранённое замечание или отмените его отправку"
            )
        operation = {
            "action": action,
            "thread_id": thread_id,
            "body": {**deepcopy(body), "operation_id": str(uuid4())},
        }
        self._path(operation)
        state = deepcopy(self.state)
        state["pending"] = operation
        state["draft"] = {}
        self._persist(state)  # Must succeed before any network write.

    def _path(self, operation):
        import re

        action, thread_id = operation["action"], operation["thread_id"]
        if action not in ("create", "replies", "state"):
            raise ValueError("Invalid review action")
        if action == "create":
            if thread_id:
                raise ValueError("Invalid review target")
            return self.repository.base + "/reviews"
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", thread_id):
            raise ValueError("Invalid review identity")
        return self.repository.base + f"/reviews/{thread_id}/{action}"

    def sync(self):
        operation = self.state["pending"]
        if operation:
            self.repository.client.request(
                "POST", self._path(operation), operation["body"]
            )
            with self._lock:
                state = deepcopy(self.state)
                state["pending"] = None
                self._persist(state)
        self.refresh()

    def refresh(self):
        items, after = [], ""
        while True:
            page = self.repository.client.request(
                "GET",
                self.repository.base + "/reviews",
                query={"after": after, "limit": 20},
            )
            if (
                not isinstance(page, dict)
                or not isinstance(page.get("items"), list)
                or not isinstance(page.get("permissions"), dict)
            ):
                raise ApiError("invalid_response")
            items.extend(page["items"])
            following = page.get("next")
            if following is None:
                break
            if (
                not isinstance(following, str)
                or following <= after
                or len(items) > 10000
            ):
                raise ApiError("invalid_response")
            after = following
        self.items = sorted(
            items, key=lambda row: (row["created_at"], row["id"]), reverse=True
        )
        self.permissions = page["permissions"]

    def restore_pending(self):
        """Restore a rejected operation as editable text without silently rebasing it."""
        if not self.pending:
            return
        if self.state["draft"]:
            raise ValueError("Сначала сохраните или удалите другой черновик замечания")
        operation = self.state["pending"]
        state = deepcopy(self.state)
        state["draft"] = {
            "action": operation["action"],
            "thread_id": operation["thread_id"],
            **operation["body"],
        }
        state["pending"] = None
        self._persist(state)

    def history(self, thread_id):
        import re

        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", thread_id):
            raise ValueError("Invalid review identity")
        items, after = [], 1
        while True:
            page = self.repository.client.request(
                "GET",
                self.repository.base + f"/reviews/{thread_id}/messages",
                query={"after": after},
            )
            if not isinstance(page, dict) or not isinstance(page.get("items"), list):
                raise ApiError("invalid_response")
            items.extend(page["items"])
            following = page.get("next")
            if following is None:
                return items
            if type(following) is not int or following <= after or len(items) > 10000:
                raise ApiError("invalid_response")
            after = following
