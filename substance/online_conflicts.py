"""Three-version conflict presentation; explicit rebasing outside server history."""

from copy import deepcopy
from PySide6.QtCore import QObject, Property, Signal, Slot


class OnlineConflicts(QObject):
    changed = Signal()
    resolved = Signal()

    def __init__(self, online):
        super().__init__(online)
        self.online = online
        self._comparison = {}
        self._error = ""

    @Property(bool, notify=changed)
    def available(self):
        return bool(self.online.repository and self.online.repository.has_conflict)

    @Property("QVariantMap", notify=changed)
    def comparison(self):
        return deepcopy(self._comparison)

    @Property(str, notify=changed)
    def status(self):
        if self._error:
            return self._error
        if self._comparison.get("error"):
            return self._comparison["error"]
        if self._comparison and not self._comparison.get("can_resolve"):
            return "Результат прежней отправки неизвестен. Сначала повторите её; черновик сохранён."
        return ""

    @Property(bool, notify=changed)
    def canResolve(self):
        return bool(
            self._comparison.get("can_resolve")
            and self.available
            and not self.online.busy
        )

    def update(self):
        self._comparison = (
            self.online.repository.comparison() if self.online.repository else {}
        )
        # Adapter defaults added on first save are preserved in the merge but
        # need no user decision. Keep actual conflicts visible, including extras.
        conflicts = {row["key"] for row in self._comparison.get("conflicts", [])}
        defaults = {
            "app_version",
            "warnings",
            "encoding",
            "bom",
            "newline",
            "trailing_newline",
            "skeleton",
            "review_settings",
            "field_order",
            "baseline",
            "original_line",
        }

        def visible(row):
            path = row["path"]
            return not (
                row["key"] not in conflicts
                and row["base"] == "Удалено / отсутствует"
                and "__substance_v1__" in path
                and path[-1] in defaults
            )

        self._comparison["changes"] = [
            row for row in self._comparison.get("changes", []) if visible(row)
        ]
        self.changed.emit()

    @Slot()
    def refresh(self):
        if not self.online.active or self.online.busy:
            return
        if not self.online.backend.flush() or not self.online.checkpoint():
            return
        self._error = ''
        # A remote cue may reference a card created by another author. Refresh
        # the library and access state alongside the document before applying it.
        self.online.refresh_shared()

    @Slot()
    def retry(self):
        self.online.retry()

    @Slot(str, "QVariantMap", str, result=bool)
    def resolve(self, token, choices, mode):
        if not self.online.active or self.online.busy:
            return False
        backend = self.online.backend
        if not backend.flush() or not self.online.checkpoint():
            return False
        repository = self.online.repository
        try:
            # Validate the desktop model before changing the durable journal.
            candidate = repository.preview_resolution(token, choices, mode)
            document = self.online._document(candidate)
            baseline = self.online._document(repository.remote["document"])
            selection = backend.current.get("id", "")
            index = backend.currentIndex
            editor = type(backend.editor)(baseline)
            editor.project_mode = True
            editor.transact(
                "Согласование версий",
                lambda d: d.__dict__.update(deepcopy(document.__dict__)),
            )
            repository.resolve(token, choices, mode)
            editor.validator = self.online.validate_edit
            editor.mark_saved()
            self.online._applying = True
            backend.editor = editor
            self.online._last_snapshot = document.to_dict()
            backend._current = next(
                (i for i, cue in enumerate(document.cues) if cue.id == selection),
                min(index, len(document.cues) - 1),
            )
            backend.selection = {backend._current} if backend._current >= 0 else set()
            backend._computed_key = None
            backend._refresh()
            self.online._applying = False
            self.online._blocked = False
            self.online._error = ""
            self.online._status = "Версии согласованы на компьютере. Прежний черновик сохранён отдельной копией."
            self._error = ""
            self.update()
            self.online.changed.emit()
            self.resolved.emit()
            return True
        except (ValueError, OSError) as exc:
            self.online._applying = False
            self._error = str(exc)
            self.changed.emit()
            return False
