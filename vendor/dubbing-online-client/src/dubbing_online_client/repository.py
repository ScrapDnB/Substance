"""Durable snapshot outbox. No Qt, credentials, or editor model dependencies.

Only one immutable operation is in flight. New edits stay in `draft` while its
reply is uncertain; the next operation receives its base after acknowledgement.
"""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading
from uuid import uuid4

from .api import ApiError
from .documents import validate_document


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".draft-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def legacy_journals(directory, context, canonical_path=None):
    """Inspect recoverable old loopback drafts without changing any files."""
    directory = Path(directory)
    from urllib.parse import urlsplit
    candidates = []
    for path in directory.glob("*/journal.json"):
        if path == canonical_path or (path.parent / "migrated-to.json").exists():
            continue
        matched = False
        try:
            journal = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(journal, dict):
                continue
            identity = journal.get("context", [])
            if len(identity) != 4 or identity[1:] != context[1:]:
                continue
            if urlsplit(identity[0]).hostname not in ("127.0.0.1", "localhost", "::1"):
                continue
            matched = True
            states = {"journal.json": journal}
            for name in ("reviews.json", "glossary.json"):
                other = path.with_name(name)
                if other.exists():
                    states[name] = json.loads(other.read_text(encoding="utf-8"))
            dirty = journal.get("pending") or journal.get("draft") != journal.get("confirmed")
            dirty = dirty or any(s.get("pending") or s.get("draft") for name, s in states.items() if name != "journal.json")
            if dirty:
                candidates.append((path, states))
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            if matched:
                raise ValueError("Не удалось прочитать прежний SSH-черновик. Исходные файлы сохранены в " + str(path.parent)) from exc
            # An unreadable unrelated journal must never be overwritten.
            continue
    return candidates


class RemoteDocumentRepository:
    def __init__(self, client, account_id, project_id, episode_id, directory, *, server_identity=None,
                 migrate_loopback=False, on_close=None, legacy_journal=None):
        self.client = client
        self._on_close = on_close
        self.context = [server_identity or client.url, account_id, project_id, episode_id]
        if not all(isinstance(v, str) and v for v in self.context):
            raise ValueError("Invalid remote document identity")
        import re

        if any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", v) for v in self.context[1:]):
            raise ValueError("Invalid remote document identity")
        key = hashlib.sha256(json.dumps(self.context).encode()).hexdigest()
        self.path = Path(directory) / key / "journal.json"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._file_lock = open(self.path.with_suffix(".lock"), "a+b")
        self._state = None
        self.remote = None
        self.base = f"/v1/projects/{project_id}/episodes/{episode_id}"
        try:
            if os.name == "nt":
                import msvcrt

                self._file_lock.seek(0)
                self._file_lock.write(b"0")
                self._file_lock.flush()
                self._file_lock.seek(0)
                msvcrt.locking(self._file_lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._file_lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._file_lock.close()
            raise ValueError("Эта серия уже открыта в другом окне Substance") from None
        try:
            if migrate_loopback and server_identity:
                self._migrate_loopback(Path(directory), selected=legacy_journal)
            if self.path.exists():
                state = json.loads(self.path.read_text(encoding="utf-8"))
                if state.get("version") != 1 or state.get("context") != self.context:
                    raise ValueError("Некорректный журнал онлайн-серии")
                if type(state.get("revision")) is not int or state["revision"] < 1:
                    raise ValueError("Некорректная базовая ревизия")
                if type(state.get("pending_rejected", False)) is not bool:
                    raise ValueError("Некорректное состояние ожидающей операции")
                for field in ("confirmed", "draft"):
                    validate_document(state[field])
                if state.get("pending"):
                    validate_document(state["pending"]["document"])
                    from uuid import UUID

                    UUID(state["pending"]["operation_id"])
                    if state["pending"]["base_revision"] != state["revision"]:
                        raise ValueError("Некорректная ожидающая операция")
                if state.get("remote") is not None:
                    self._validate_reply(state["remote"])
                    self.remote = deepcopy(state["remote"])
                self._state = state
        except BaseException:
            self.close()
            raise

    def _migrate_loopback(self, directory, *, selected=None):
        """Keep old files as recovery copies; move every outbox as one unit.

        Old clients did not store the SSH host. Match all three immutable IDs,
        require a loopback URL, and refuse to guess between distinct drafts.
        The old journal lock also protects review and glossary operations.
        """
        candidates = legacy_journals(directory, self.context, self.path)
        recovery = self.path.with_name("legacy-recovery.json")
        if recovery.exists() and selected is None:
            saved = json.loads(recovery.read_text(encoding="utf-8"))
            if saved.get("context") != self.context:
                raise ValueError("Не совпал контекст сохранённых копий черновика")
            alternatives = set(saved.get("alternatives", []))
            candidates = [(path, states) for path, states in candidates if str(path) not in alternatives]
        alternatives = []
        if selected is not None:
            matches = [(path, states) for path, states in candidates if path.resolve() == Path(selected).resolve()]
            if len(matches) != 1:
                raise ValueError("Выбранный прежний черновик больше недоступен")
            alternatives = [str(path) for path, _ in candidates if path != matches[0][0]]
            candidates = matches
        if len(candidates) > 1:
            raise ValueError("Найдено несколько прежних SSH-черновиков этой серии. "
                             "Они сохранены в " + str(directory) + "; выберите черновик для восстановления перед открытием серии.")
        if not candidates:
            return
        path, states = candidates[0]
        with open(path.with_suffix(".lock"), "a+b") as lock:
            try:
                if os.name == "nt":
                    import msvcrt
                    lock.write(b"0"); lock.flush(); lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ValueError("Эта серия уже открыта в другом окне Substance") from None
            if alternatives:
                atomic_json(recovery, {"context": self.context, "alternatives": alternatives})
            # Read again under the lock: an older editor may have checkpointed.
            for name in states:
                source = path.with_name(name)
                state = json.loads(source.read_text(encoding="utf-8"))
                if state.get("context") != states["journal.json"]["context"]:
                    raise ValueError("Не совпали контексты прежнего SSH-черновика")
                state["context"] = self.context
                destination = self.path.with_name(name)
                if destination.exists():
                    current = json.loads(destination.read_text(encoding="utf-8"))
                    if current != state:
                        raise ValueError("У серии есть два разных черновика. Прежний сохранён в " + str(path.parent))
                else:
                    atomic_json(destination, state)
            atomic_json(path.parent / "migrated-to.json", {"context": self.context})

    def _persist(self, state):
        atomic_json(self.path, state)
        self._state = state

    @property
    def snapshot(self):
        with self._lock:
            return deepcopy(self._state["draft"]) if self._state else None

    @property
    def revision(self):
        with self._lock:
            return self._state["revision"] if self._state else 0

    @property
    def pending(self):
        with self._lock:
            return bool(
                self._state
                and (
                    self._state["pending"]
                    or self._state["draft"] != self._state["confirmed"]
                )
            )

    def open(self):
        return self.refresh_remote()

    def _remember_remote(self, result):
        self._validate_reply(result)
        with self._lock:
            state = deepcopy(self._state)
            state["remote"] = deepcopy(result)
            self._persist(state)
            self.remote = deepcopy(result)

    def refresh_remote(self, *, defer=False):
        """Reading never reserves an episode, including with a local draft."""
        result = self.client.request("GET", self.base + "/document")
        self._validate_reply(result)
        with self._lock:
            if not self._state:
                self._persist(
                    {
                        "version": 1,
                        "context": self.context,
                        "revision": result["revision"],
                        "confirmed": result["document"],
                        "draft": result["document"],
                        "pending": None,
                    }
                )
            elif not self.pending and defer and result["revision"] != self.revision:
                self._remember_remote(result)
                return deepcopy(result["document"])
            elif not self.pending:
                state = deepcopy(self._state)
                state.update(
                    revision=result["revision"],
                    confirmed=result["document"],
                    draft=result["document"],
                    remote=None,
                )
                self._persist(state)
                self.remote = None
            elif result["revision"] != self.revision:
                self._remember_remote(result)
        return self.snapshot

    def adopt_remote(self):
        """UI acknowledgement of a clean remote refresh. Until then new typing
        still checkpoints against its old displayed base, never the unseen one.
        """
        with self._lock:
            if self.pending or not self.remote:
                raise ValueError('Черновик изменился во время обновления')
            remote = deepcopy(self.remote)
            state = deepcopy(self._state)
            state.update(revision=remote['revision'], confirmed=remote['document'],
                         draft=remote['document'], remote=None)
            self._persist(state)
            self.remote = None
            return self.snapshot

    @property
    def has_conflict(self):
        with self._lock:
            return bool(
                self.remote
                and self.remote["revision"] != self.revision
                and self.pending
            )

    @property
    def can_resolve(self):
        with self._lock:
            return bool(
                self.has_conflict
                and (not self._state["pending"] or self._state.get("pending_rejected"))
            )

    def _comparison_token(self):
        return hashlib.sha256(
            json.dumps(
                {
                    "base": self._state["confirmed"],
                    "draft": self._state["draft"],
                    "revision": self.revision,
                    "remote": self.remote,
                    "pending": self._state["pending"],
                    "rejected": self._state.get("pending_rejected", False),
                },
                sort_keys=True,
                ensure_ascii=False,
            ).encode()
        ).hexdigest()

    def comparison(self):
        from .merge import merge_documents

        with self._lock:
            if not self.has_conflict:
                return {}
            try:
                _, conflicts, changes = merge_documents(
                    self._state["confirmed"], self.snapshot, self.remote["document"]
                )
                error = ""
            except ValueError as exc:
                conflicts, changes, error = [], [], str(exc)
            return {
                "token": self._comparison_token(),
                "base_revision": self.revision,
                "server_revision": self.remote["revision"],
                "conflicts": conflicts,
                "changes": changes,
                "can_resolve": self.can_resolve,
                "error": error,
            }

    def preview_resolution(self, token, choices, mode="merge"):
        from .merge import merge_documents

        with self._lock:
            if not self.can_resolve or token != self._comparison_token():
                raise ValueError(
                    "Черновик или состояние отправки изменились. Обновите сравнение"
                )
            if mode == "server":
                return deepcopy(self.remote["document"])
            if mode == "mine":
                return self.snapshot
            if mode != "merge":
                raise ValueError("Некорректное действие согласования")
            candidate, conflicts, _ = merge_documents(
                self._state["confirmed"],
                self.snapshot,
                self.remote["document"],
                choices,
            )
            if any(choices.get(c["key"]) not in ("mine", "server") for c in conflicts):
                raise ValueError("Выберите значение каждого конфликтующего поля")
            return candidate

    def resolve(self, token, choices, mode="merge"):
        """Rebase locally after an explicit choice, preserving an immutable recovery copy.
        A result-unknown operation must first be acknowledged or definitively rejected.
        The next PUT checks permissions and the chosen server revision.
        """
        with self._lock:
            if not self.can_resolve:
                raise ValueError(
                    "Сначала повторите прежнюю отправку: её результат ещё неизвестен"
                )
            if token != self._comparison_token():
                raise ValueError(
                    "Черновик или серверная версия изменились. Обновите сравнение"
                )
            remote = deepcopy(self.remote)
            candidate = self.preview_resolution(token, choices, mode)
            validate_document(candidate)
            if candidate["source_lines"] != remote["document"]["source_lines"]:
                raise ValueError("Согласование не может заменять исходник")
            originals = {c["id"]: c.get("original") for c in remote["document"]["cues"]}
            if any(
                c["id"] in originals and c.get("original") != originals[c["id"]]
                for c in candidate["cues"]
            ):
                raise ValueError(
                    "Согласование не может изменять оригинал существующей реплики"
                )
            recovery = self.path.with_name("recovery-" + uuid4().hex + ".json")
            atomic_json(
                recovery, self._state
            )  # if either write fails the old journal stays authoritative
            state = deepcopy(self._state)
            state.update(
                revision=remote["revision"],
                confirmed=remote["document"],
                draft=candidate,
                pending=None,
                pending_rejected=False,
                remote=None,
                recovery=str(recovery.name),
            )
            self._persist(state)
            self.remote = None
            return self.snapshot

    def checkpoint(self, document):
        validate_document(document)
        with self._lock:
            if not self._state:
                raise ValueError("Документ ещё не открыт")
            if document == self._state["draft"]:
                return
            state = deepcopy(self._state)
            state["draft"] = deepcopy(document)
            self._persist(state)

    def _validate_reply(self, result):
        if (
            not isinstance(result, dict)
            or result.get("project_id") != self.context[2]
            or result.get("episode_id") != self.context[3]
            or type(result.get("revision")) is not int
            or result["revision"] < 1
        ):
            raise ApiError("invalid_response")
        validate_document(result["document"])

    def sync(self, *, defer_remote=False):
        with self._lock:
            if not self._state:
                raise ValueError("Документ ещё не открыт")
            operation = deepcopy(self._state["pending"])
        if not operation:
            self.refresh_remote(defer=defer_remote)
            if self.has_conflict:
                raise ApiError(
                    "revision_conflict",
                    409,
                    {"current_revision": self.remote["revision"]},
                )
            if defer_remote and self.remote and self.remote["revision"] != self.revision:
                return deepcopy(self.remote["document"])
            with self._lock:
                if not self.pending:
                    return self.snapshot
                operation = {
                    "operation_id": str(uuid4()),
                    "base_revision": self.revision,
                    "document": self.snapshot,
                }
                state = deepcopy(self._state)
                state.update(pending=operation, pending_rejected=False)
                self._persist(state)
        # Retry first: the server resolves operation_id before write rights.
        # A newer server revision alone cannot prove the lost PUT did not commit.
        with self._lock:
            if self._state.get("pending_rejected"):
                state = deepcopy(self._state)
                state["pending_rejected"] = False
                self._persist(state)  # a new attempt makes the outcome unknown again
        try:
            result = self.client.request("PUT", self.base + "/document", operation)
        except ApiError as exc:
            if exc.code != "revision_conflict":
                raise
            with self._lock:
                state = deepcopy(self._state)
                state["pending_rejected"] = True
                self._persist(state)
            self.refresh_remote()
            raise ApiError(
                "revision_conflict", 409,
                {"current_revision": self.remote["revision"] if self.remote else self.revision},
            ) from exc
        self._validate_reply(result)
        if result["revision"] != operation["base_revision"] + 1:
            raise ApiError("invalid_response")
        with self._lock:
            state = deepcopy(self._state)
            state.update(
                revision=result["revision"],
                confirmed=result["document"],
                pending=None,
                pending_rejected=False,
                remote=None,
            )
            if state["draft"] == operation["document"]:
                state["draft"] = deepcopy(result["document"])
            self._persist(state)
            self.remote = None
        return self.snapshot

    def workflow(self, action, reason=""):
        if self.pending:
            raise ValueError("Сначала дождитесь подтверждения всех правок сервером")
        result = self.client.request(
            "POST",
            self.base + "/workflow",
            {"action": action, "revision": self.revision, "reason": reason},
        )
        return result

    def release(self):
        """Compatibility for existing callers: server reservations no longer exist."""

    def close(self):
        # OS releases the advisory lock on crash, too. Closing is independent of
        # network availability; the durable journal is never deleted here.
        if not self._file_lock.closed:
            self._file_lock.close()
        callback, self._on_close = self._on_close, None
        if callback:
            callback()
