"""Qt presentation of revision-anchored server remarks, outside document Undo."""

from copy import deepcopy

from PySide6.QtCore import QObject, Property, Signal, Slot

from .repositories import online_client


class OnlineReviews(QObject):
    changed = Signal()
    saveDraftRequested = Signal()

    def __init__(self, online):
        super().__init__(online)
        self.online = online
        self.repository = None
        self._error = ""
        self._retry_blocked = False
        self._history = {}
        self._unavailable_draft = {}
        self._restore_allowed = False

    def attach(self, repository):
        self.repository = repository
        self._error, self._retry_blocked = "", False
        self._restore_allowed = False
        self._history = {}
        self.changed.emit()

    @Property(bool, notify=changed)
    def supported(self):
        return self.repository is not None and self.online.reviewEnabled

    @Property(bool, notify=changed)
    def pending(self):
        return bool(self.repository and self.repository.pending)

    @Property(bool, notify=changed)
    def canRestore(self):
        return self.pending and self._restore_allowed

    @Property(str, notify=changed)
    def status(self):
        return self._error or (
            "Замечание сохранено на компьютере · ожидает отправки"
            if self.pending
            else ""
        )

    @Property("QVariantMap", notify=changed)
    def draft(self):
        return (
            deepcopy(self.repository.state["draft"])
            if self.repository
            else self._unavailable_draft
        )

    def _permission(self, key):
        return bool(self.online.reviewEnabled and self.repository and self.repository.permissions.get(key))

    @Property(bool, notify=changed)
    def canCreate(self):
        return (
            self._permission("can_create")
            and not self.pending
            and not self.online.pending
            and self.online._episode_state.get("accepted_revision") is None
        )

    @Property(bool, notify=changed)
    def canReopen(self):
        return (
            self.canDecide
            and self.online._episode_state.get("accepted_revision") is None
        )

    @Property(bool, notify=changed)
    def canReply(self):
        return self._permission("can_reply") and not self.pending

    @Property(bool, notify=changed)
    def canDecide(self):
        return self._permission("can_decide") and not self.pending

    @Property("QVariantList", notify=changed)
    def entries(self):
        if not self.repository:
            return []
        cues = self.online.backend.editor.document.cues
        positions = {cue.id: i + 1 for i, cue in enumerate(cues)}
        result = []
        for row in self.repository.items:
            value = deepcopy(row)
            number = positions.get(row["cue_id"])
            value["archived"] = number is None
            value["caption"] = (
                f"Реплика {number}" if number else "Удалённая реплика"
            ) + f" · ревизия {row['revision']}"
            value["contextText"] = (
                row["context"].get("translation")
                if row["context"].get("translation") is not None
                else row["context"].get("text", "")
            )
            value["contextText"] = (value["contextText"] or "").replace(r"\N", "\n")
            if row["id"] in self._history:
                old = self._history[row["id"]]
                value["messages"] = sorted(
                    {m["version"]: m for m in [*old, *row["messages"]]}.values(),
                    key=lambda m: m["version"],
                )
                value["has_older_messages"] = False
            result.append(value)
        return result

    @Slot("QVariantMap", result=bool)
    def saveDraft(self, draft):
        if not self.repository:
            self._unavailable_draft = deepcopy(draft)
            return True
        try:
            self.repository.save_draft(draft)
            self.changed.emit()
            return True
        except (OSError, ValueError) as exc:
            self._error = "Не удалось сохранить черновик замечания: " + str(exc)
            self.changed.emit()
            return False

    @Slot(str, str, str, str, int, result=bool)
    def createAt(self, kind, text, replacement, cue_id, revision):
        if (
            revision != self.online.revision
            or cue_id != self.online.backend.current.get("id", "")
        ):
            self.online.backend.show_error(
                "Обновите привязку замечания к текущей ревизии"
            )
            return False
        return self.create(kind, text, replacement)

    @Slot(str, str, str, result=bool)
    def create(self, kind, text, replacement):
        if not self.canCreate or not self.online.backend.flush():
            return False
        if self.online.pending:
            self.online.backend.show_error("Сначала подтвердите текст серии на сервере")
            return False
        cue_id = self.online.backend.current.get("id", "")
        if (
            not cue_id
            or kind not in ("note", "proposal")
            or not text.strip()
            or len(text) > 10000
        ):
            return False
        body = {
            "revision": self.online.revision,
            "cue_id": cue_id,
            "kind": kind,
            "text": text.strip(),
        }
        if kind == "proposal":
            body["replacement"] = replacement.replace("\n", r"\N")
        return self._enqueue("create", body)

    @Slot(str, str, str, int, result=bool)
    def respondAt(self, thread_id, state, text, version):
        row = (
            next((r for r in self.repository.items if r["id"] == thread_id), None)
            if self.repository
            else None
        )
        if not row or version != row["version"]:
            self.online.backend.show_error(
                "В обсуждении появились изменения. Обновите привязку черновика"
            )
            return False
        return self.respond(thread_id, state, text)

    @Slot(str, str, str, result=bool)
    def respond(self, thread_id, state, text):
        if not self.repository or not text.strip() or len(text) > 10000:
            return False
        row = next((r for r in self.repository.items if r["id"] == thread_id), None)
        if not row or not (self.canDecide if state else self.canReply):
            return False
        body = {"base_version": row["version"], "text": text.strip()}
        if state:
            if state not in ("open", "resolved", "rejected"):
                return False
            body["state"] = state
        return self._enqueue("state" if state else "replies", body, thread_id)

    def _enqueue(self, action, body, thread_id=""):
        if not self.repository or self.pending or self.online.busy:
            return False
        try:
            self.repository.enqueue(action, body, thread_id)
        except (ValueError, OSError) as exc:
            self._error = str(exc)
            self.changed.emit()
            return False
        self._retry_blocked, self._error = False, ""
        self.changed.emit()
        self.refresh()
        return True

    def poll(self):
        """Called on the ordered online worker; failures must not block document sync."""
        if not self.repository:
            return "", False, False
        try:
            if self._retry_blocked:
                self.repository.refresh()
                return self._error, True, self._restore_allowed
            else:
                self.repository.sync()
            return "", False, False
        except Exception as exc:
            online_client()
            from dubbing_online_client import ApiError

            blocked = isinstance(exc, ApiError) and exc.status in (
                400,
                401,
                403,
                404,
                409,
                422,
            )
            try:
                self.repository.refresh()
            except Exception:
                pass
            return (
                str(exc),
                blocked,
                isinstance(exc, ApiError)
                and exc.code
                in (
                    "review_version_conflict",
                    "revision_conflict",
                    "review_cue_invalid",
                    "validation_failed",
                    "review_state_unchanged",
                    "review_episode_accepted",
                ),
            )

    def updated(self, outcome):
        self._error, self._retry_blocked, self._restore_allowed = outcome
        self.changed.emit()
        self.online.backend._computed_key = None
        self.online.backend._refresh()

    @Slot()
    def refresh(self):
        if not self.repository or self.online.busy:
            return
        repository = self.repository

        def operation():
            project = repository.repository.client.request(
                "GET", f"/v1/projects/{self.online.context['project_id']}"
            )
            return self.poll(), project

        def done(result):
            outcome, project = result
            self.online._update_project(project)
            self.updated(outcome)

        self.online._run(operation, done)

    @Slot()
    def retry(self):
        self._retry_blocked = False
        self.refresh()

    @Slot(result=bool)
    def restorePending(self):
        if not self.repository or self.online.busy or not self.canRestore:
            return False
        try:
            self.repository.restore_pending()
            self._error, self._retry_blocked = "", False
            self.changed.emit()
            return True
        except (OSError, ValueError) as exc:
            self._error = str(exc)
            self.changed.emit()
            return False

    @Slot(str)
    def loadHistory(self, thread_id):
        if not self.repository or self.online.busy:
            return
        repository = self.repository

        def operation():
            try:
                return repository.history(thread_id), ""
            except Exception as exc:
                return [], str(exc)

        def done(result):
            messages, error = result
            self._error = error
            if not error:
                self._history[thread_id] = messages
            self.changed.emit()

        self.online._run(operation, done)
