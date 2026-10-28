"""Qt lifecycle for independently connected remote episodes."""
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

from .document import Document
from .repositories import online_client, remote_document


class OnlineController(QObject):
    changed = Signal()
    completed = Signal(object)
    workflowCompleted = Signal(str)
    closeReady = Signal()

    def __init__(self, backend):
        super().__init__(backend)
        self.backend = backend
        self.repository = None
        self.context = {}
        self.glossary = []
        from .online_reviews import OnlineReviews
        self.reviews = OnlineReviews(self)
        from .online_glossary import OnlineGlossary
        self.glossary_session = OnlineGlossary(self)
        from .online_conflicts import OnlineConflicts
        self.conflicts = OnlineConflicts(self)
        self._generation = 0
        self._project_state = {}
        self._episode_state = {}
        self.images = {}
        self._last_snapshot = None
        self._busy = False
        self._status = ""
        self._error = ""
        self._blocked = False
        self._closing = False
        self._close_requested = False
        self._allow_local_close = False
        self._close_timer_was_active = False
        self._applying = False
        self._session_persisted = False
        self._future = None
        self._callback = None
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="substance-online")
        self.completed.connect(self._finished)
        self.changed.connect(self.reviews.changed.emit)
        self.timer = QTimer(self, interval=30000)
        self.timer.timeout.connect(self.sync)

    @Property(QObject, constant=True)
    def conflictSession(self):
        return self.conflicts

    @Property(QObject, constant=True)
    def glossarySession(self):
        return self.glossary_session

    @Property(QObject, constant=True)
    def reviewSession(self):
        return self.reviews

    @Property(bool, notify=changed)
    def active(self):
        return self.repository is not None

    @Property(str, notify=changed)
    def title(self):
        names = (self._project_state.get("name") or self.context.get("project_name"),
                 self._episode_state.get("name") or self.context.get("episode_name"))
        return " — ".join(name.strip() for name in names if isinstance(name, str) and name.strip()) or "Онлайн-серия"

    @Property(bool, notify=changed)
    def busy(self):
        return self._busy

    @Property(str, notify=changed)
    def status(self):
        if self._error:
            return self._error
        return self._status + (" · сессия до закрытия приложения" if self.active and not self._session_persisted else "")

    @Property(bool, notify=changed)
    def pending(self):
        return bool(self.repository and self.repository.pending)

    @Property(bool, notify=changed)
    def blocked(self):
        return self._blocked

    @Property(bool, notify=changed)
    def canResume(self):
        return (self.backend.data_dir / "online-last.json").is_file()

    @Property(int, notify=changed)
    def revision(self):
        return self.repository.revision if self.repository else 0

    @Property(bool, notify=changed)
    def reviewEnabled(self):
        return bool(self._project_state.get("review_enabled", True))

    def _assigned(self, kind):
        if kind == "editing" and not self.reviewEnabled:
            return False
        roles = set(self._project_state.get("roles", []))
        return bool(self._project_state.get("server_admin") or roles.intersection({"admin", "chief_editor"})
                    or ({"translation": "translator", "editing": "editor"}[kind] in roles
                        and self._episode_state.get("tasks", {}).get(kind) == self.context.get("account_id")))

    @Property(bool, notify=changed)
    def canStartTranslation(self):
        return self.active and self._assigned("translation") and self._episode_state.get("translation_status") == "not_started"

    @Property(bool, notify=changed)
    def canSubmit(self):
        return self.active and self._assigned("translation") and (self._episode_state.get("translation_status") in ("in_progress", "changes_requested") or not self.reviewEnabled and self._episode_state.get("translation_status") == "ready" and self._episode_state.get("submitted_revision") != self._episode_state.get("revision"))

    @Property(bool, notify=changed)
    def canReview(self):
        return self.active and self._assigned("editing") and self._episode_state.get("translation_status") == "ready" and self._episode_state.get("review_status") == "pending"

    @Property(bool, notify=changed)
    def canAccept(self):
        return self.active and self._assigned("editing") and self._episode_state.get("translation_status") == "ready" and self._episode_state.get("review_status") == "in_review"

    @Property(bool, notify=changed)
    def canReturn(self):
        return self.active and self._assigned("editing") and self._episode_state.get("translation_status") == "ready" and self._episode_state.get("accepted_revision") is None

    @Property(bool, notify=changed)
    def canReopenWork(self):
        roles = set(self._project_state.get("roles", []))
        return self.active and not self._project_state.get("archived") and bool(self._project_state.get("server_admin") or roles.intersection({"admin", "chief_editor"}))

    def _update_project(self, project):
        self._project_state = project
        self._episode_state = next((e for e in project.get("episodes", []) if e["id"] == self.context.get("episode_id")), {})

    def _run(self, operation, callback):
        if self._busy or self._closing:
            return
        self._busy, self._callback = True, callback
        self._callback_generation = self._generation
        self.changed.emit()
        self._future = self._executor.submit(operation)
        self._future.add_done_callback(self._deliver)

    def _deliver(self, future):
        if self._closing:
            try:
                result = future.result()
                if isinstance(result, dict) and "repository" in result:
                    result["repository"].close()
            except Exception:
                pass
            return
        try:
            self.completed.emit(future)
        except RuntimeError:
            pass  # the application has already disposed the Qt context

    @Slot(object)
    def _finished(self, future):
        self._future = None
        self._busy = False
        if self._closing:
            try:
                result = future.result()
                if isinstance(result, dict) and "repository" in result:
                    result["repository"].close()
            except Exception:
                pass
            if self.repository:
                self.repository.close()
            return
        if self._callback_generation != self._generation:
            try:
                result = future.result()
                if isinstance(result, dict) and "repository" in result:
                    result["repository"].close()
            except Exception:
                pass
            self._callback = None
            self.changed.emit()
            return
        failure = None
        try:
            self._callback(future.result())
            self.backend._message = self._status
            self.backend.changed.emit()
        except Exception as exc:
            self._error = str(exc)
            from dubbing_online_client import ApiError
            self._blocked = isinstance(exc, ApiError) and exc.status in (401, 403, 404, 409)
            if isinstance(exc, ApiError) and exc.status == 401 and self.context.get("account_id"):
                from dubbing_online_client.credentials import SessionVault
                vault = SessionVault()
                # Another episode/device may already have stored a renewed
                # session for this account. Do not remove its credential.
                token = self.repository.client.token if self.repository else ''
                identity = self.context.get('server_identity', self.context['server_url'])
                if token and vault.get(identity, self.context['account_id']) == token:
                    vault.delete(identity, self.context['account_id'])
            failure = self._error
            if not self._close_requested:
                self.backend.show_error(self._error)
        self._callback = None
        self.conflicts.update()
        self.changed.emit()
        if self._close_requested and self._continue_close(error=failure):
            self.closeReady.emit()

    def connect(self, launch, *, resume=False):
        online_client()
        from dubbing_online_client.credentials import SessionVault
        try:
            launch = self._choose_legacy(launch)
        except (ValueError, OSError) as exc:
            self.backend.show_error(str(exc))
            return
        if launch is None:
            return
        self._status, self._error = "Подключение к онлайн-серии…", ""

        def operation():
            from dubbing_online_client.editor_identity import server_identity
            identity = server_identity(launch["server_url"], launch.get("ssh"))
            if launch.get("server_identity", identity) != identity:
                raise ValueError("Не совпала идентичность онлайн-сервера")
            vault = SessionVault()
            transport = None
            if launch.get("ssh"):
                from .online_transport import OnlineTransport
                secret = vault.get_transport(identity, launch["account_id"]) if resume else launch.get("ssh_secret")
                if secret is None:
                    raise ValueError("Откройте серию из DubbingManager для нового SSH-входа. Черновик сохранён.")
                transport = OnlineTransport(launch["ssh"], launch["ssh_directory"], secret)
            try:
                return self._connect_repository(launch, resume, identity, vault, transport)
            except BaseException:
                if transport:
                    transport.close()
                raise

        def opened(result):
            self._opened_repository(result)

        self._run(operation, opened)

    def _choose_legacy(self, launch):
        """Choose between old copies on the GUI thread, before consuming a code."""
        if not launch.get("ssh") or not launch.get("account_id"):
            return launch
        import hashlib
        from dubbing_online_client.editor_identity import server_identity
        from dubbing_online_client.repository import legacy_journals
        context = [server_identity(launch["server_url"], launch["ssh"]), launch["account_id"],
                   launch["project_id"], launch["episode_id"]]
        directory = self.backend.data_dir / "online"
        key = hashlib.sha256(json.dumps(context).encode()).hexdigest()
        if (directory / key / "journal.json").exists():
            return launch
        candidates = legacy_journals(directory, context)
        if len(candidates) < 2:
            return launch
        from PySide6.QtWidgets import QInputDialog
        labels = []
        for path, states in candidates:
            state = states["journal.json"]
            text = next((cue.get("translation") for cue in state.get("draft", {}).get("cues", []) if cue.get("translation")), "Пометки или глоссарий")
            labels.append(f"Ревизия {state['revision']} · {text[:70]} · {path.parent.name[:10]}")
        selected, accepted = QInputDialog.getItem(None, "Восстановление онлайн-черновика",
            "Найдено несколько прежних копий серии. Выберите текст для восстановления.\n"
            "Все исходные копии останутся на компьютере.", labels, 0, False)
        return {**launch, "legacy_journal": str(candidates[labels.index(selected)][0])} if accepted else None

    def _connect_repository(self, launch, resume, identity, vault, transport):
        from dubbing_online_client import ApiClient, ApiError
        from dubbing_online_client.repository import RemoteDocumentRepository, atomic_json
        client = ApiClient(transport.url if transport else launch["server_url"])
        info = client.negotiate()
        if not {"editor_handoff", "document_cas_v1", "document_revisions"}.issubset(info.get("capabilities", [])):
            raise ApiError("incompatible_server")
        context = {k: launch[k] for k in ("server_url", "project_id", "episode_id", "episode_name")}
        context["server_identity"] = identity
        if launch.get("ssh"):
            # Transport parameters and host keys are public local metadata.
            # The password and passphrase remain in memory or the OS vault.
            context.update(ssh={k: v for k, v in launch["ssh"].items() if k in
                ("host", "ssh_user", "ssh_port", "api_port", "fingerprint", "key_file")},
                ssh_directory=launch["ssh_directory"])
        # Device-local context only; this path never enters a server document.
        if isinstance(launch.get("media_path"), str) and launch["media_path"]:
            context["media_path"] = launch["media_path"]
        if resume:
            client.token = vault.get(identity, launch["account_id"])
            if not client.token:
                raise ValueError("Откройте серию из DubbingManager для нового входа. Локальный черновик сохранён.")
            account = client.request("GET", "/v1/auth/me")
            if account["id"] != launch["account_id"]:
                raise ValueError("Сессия принадлежит другому аккаунту")
        else:
            auth = client.request("POST", "/v1/auth/editor/exchange", {"code": launch["code"], "device": "Substance"})
            if (auth.get("project_id"), auth.get("episode_id")) != (launch["project_id"], launch["episode_id"]):
                raise ApiError("invalid_response")
            client.token = auth["access_token"]
            account = auth["user"]
            if launch.get("account_id") and launch["account_id"] != account["id"]:
                raise ValueError("Сессия принадлежит другому аккаунту")
        context.update(account_id=account["id"])
        saved = vault.put(identity, account["id"], client.token)
        if transport:
            saved = vault.put_transport(identity, account["id"], transport.secret) and saved
        repository = RemoteDocumentRepository(client, account["id"], context["project_id"], context["episode_id"],
            self.backend.data_dir / "online", server_identity=identity,
            migrate_loopback=transport is not None, on_close=transport.close if transport else None,
            legacy_journal=launch.get("legacy_journal"))
        try:
            repository.open()
            glossary_repository = None
            if "glossary_operations" in info.get("capabilities", []):
                from dubbing_online_client.glossary import RemoteGlossary
                glossary_repository = RemoteGlossary(repository)
                glossary_repository.refresh()
            glossary = client.request("GET", f'/v1/projects/{context["project_id"]}/glossary')
            images = self._images(client, context, glossary)
            project = client.request("GET", f'/v1/projects/{context["project_id"]}')
            reviews = None
            if "review_threads" in info.get("capabilities", []):
                from dubbing_online_client.reviews import RemoteReviews
                reviews = RemoteReviews(repository)
                reviews.refresh()
            # Persist only the context, never the code, password or token.
            atomic_json(self.backend.data_dir / "online-last.json", context)
            return {"repository": repository, "context": context, "glossary": glossary, "images": images, "saved": saved, "project": project, "reviews": reviews, "glossary_repository": glossary_repository}
        except BaseException:
            repository.close()
            raise

    def _opened_repository(self, result):
        self._session_persisted = result["saved"]
        self.context, self.glossary, self.images = result["context"], result["glossary"], result["images"]
        self._update_project(result["project"])
        self._applying = True
        # Load before attaching, so replacing a local document doesn't close
        # the newly acquired repository.
        try:
            media_path = self.context.get("media_path", "")
            media = {"path": media_path} if media_path and Path(media_path).is_file() else {}
            document = self._document(result["repository"].snapshot, media=media)
        except BaseException:
            result["repository"].close()
            self._applying = False
            raise
        self.backend._set_document(document, "")
        self.repository = result["repository"]
        self.reviews.attach(result["reviews"])
        self.glossary_session.attach(result["glossary_repository"])
        self.backend.editor.project_mode = True
        self.backend.editor.validator = self.validate_edit
        self._last_snapshot = self.backend.editor.document.to_dict()
        self.backend.setMode("translation")
        if media:
            self.backend.media_controller.open(media["path"])
        else:
            self.backend.media_controller.clear()
        self._applying = False
        self._status = "Черновик сохранён на компьютере" if self.pending else f"На сервере · ревизия {self.revision}"
        self.backend.changed.emit()
        self.timer.start()
        QTimer.singleShot(0, self.sync)


    def _images(self, client, context, glossary):
        images = {}
        for entry in glossary:
            for portrait in entry["data"].get("portraits", []):
                for key in ("source", "image"):
                    asset = portrait[key]
                    if asset not in images:
                        images[asset] = self.images[asset] if asset in self.images else client.image(context["project_id"], asset)
        return images

    def _document(self, wire, *, media=None):
        from dubbing_online_client.documents import to_substance
        snapshot = to_substance(wire)
        # Refresh/conflict adoption must preserve this device's media, including
        # a video chosen in Substance after launch. Initial opens pass it explicitly.
        if media is None:
            media = self.backend.editor.document.media if self.active else {}
        snapshot["media"] = deepcopy(media)
        snapshot["characters"] = [{"id": row["id"], **deepcopy(row["data"]), "primary": row["data"].get("primary") or ""}
                                   for row in self.glossary if row["kind"] == "character"]
        snapshot["terms"] = [{"id": row["id"], **deepcopy(row["data"])} for row in self.glossary if row["kind"] == "term"]
        snapshot["images"] = deepcopy(self.images)
        names = {c["id"]: c["name"] for c in snapshot["characters"]}
        for cue in snapshot["cues"]:
            cue["character"] = names.get(cue["character_id"], "")
            cue["extras"] = cue.get("extras", {})
            cue["extras"].pop("authoring", None)
        return Document.from_dict(snapshot)

    def validate_edit(self, document):
        if not self.active:
            return
        current = self.backend.editor.document
        if document.characters != current.characters:
            raise ValueError("Общие карточки редактируются в окне онлайн-глоссария")
        if document.reviews != current.reviews:
            raise ValueError("Общие замечания сохраняются отдельно от текста серии")
        remote_document(document.to_dict(), self.repository.snapshot)

    def checkpoint(self):
        if not self.active or self._applying:
            return True
        snapshot = self.backend.editor.document.to_dict()
        if snapshot == self._last_snapshot:
            return True
        try:
            self.repository.checkpoint(remote_document(snapshot, self.repository.snapshot))
        except (OSError, ValueError) as exc:
            self._error = "Не удалось сохранить онлайн-черновик: " + str(exc)
            self.changed.emit()
            return False
        self._last_snapshot = snapshot
        self.backend.editor.mark_saved()  # saved locally; server state is separate
        self._status, self._error = "На компьютере · ожидает отправки", ""
        self.conflicts.changed.emit()
        self.changed.emit()
        return True

    @Slot()
    def sync(self):
        if not self.active or self._busy:
            return
        if self._blocked:
            self.refresh_shared()
            return
        if not self.backend.flush() or not self.checkpoint():
            return
        repository = self.repository
        editor = self.backend.editor
        revision = editor.revision
        had_edits = repository.pending
        base_revision = repository.revision
        self._status, self._error = "Синхронизация…", ""

        def operation():
            wire = repository.sync(defer_remote=True)
            project = repository.client.request("GET", f'/v1/projects/{self.context["project_id"]}')
            return wire, project, self.reviews.poll(), self.glossary_session.poll()

        def synced(result):
            wire, project, reviews_outcome, glossary_outcome = result
            self._update_project(project)
            self.glossary_session.updated(glossary_outcome)
            flushed = self.backend.flush()
            if flushed and not repository.pending and self.backend.editor is editor and editor.revision == revision:
                restored = self._document(wire)
                # Normal acknowledgements preserve selection and the entire Undo
                # chain. Only remote changes on a clean document replace it.
                if not had_edits and repository.remote and repository.remote["revision"] != base_revision:
                    repository.adopt_remote()
                    self._applying = True
                    self.backend.editor = type(editor)(restored)
                    self.backend.editor.project_mode = True
                    self.backend.editor.validator = self.validate_edit
                    self._last_snapshot = restored.to_dict()
                    self.backend._refresh()
                    self._applying = False
            self._status = "На компьютере · ожидает отправки" if repository.pending else f"На сервере · ревизия {repository.revision}"
            self._error = ""
            if repository.has_conflict:
                self._blocked = True
                self._error = "Во время обновления появились локальные правки. Сравните версии."
            self.reviews.updated(reviews_outcome)

        self._run(operation, synced)

    def apply_glossary(self, rows, images):
        """Update shared metadata in all Undo snapshots without changing episode edits."""
        if rows == self.glossary and images == self.images:
            return
        self.glossary, self.images = deepcopy(rows), deepcopy(images)
        template = self._document(self.repository.snapshot)
        documents = [self.backend.editor.document]
        for entry in self.backend.editor.undo_stack + self.backend.editor.redo_stack:
            documents.extend([entry.before, entry.after])
        names = {c.id: c.name for c in template.characters}
        for document in documents:
            document.characters = deepcopy(template.characters)
            document.images = deepcopy(template.images)
            document.extras['terms'] = deepcopy(template.extras.get('terms', []))
            for cue in document.cues:
                if cue.character_id in names:
                    cue.character = names[cue.character_id]
        self._last_snapshot = self.backend.editor.document.to_dict()
        self.backend._refresh()

    def refresh_shared(self):
        if self.busy or not self.active:
            return
        repository, editor = self.repository, self.backend.editor
        revision, base_revision = editor.revision, repository.revision
        had_edits = repository.pending
        def operation():
            wire = repository.refresh_remote(defer=True)
            project = repository.client.request('GET', f"/v1/projects/{self.context['project_id']}")
            return wire, project, self.reviews.poll(), self.glossary_session.poll()
        def done(result):
            wire, project, reviews, glossary = result
            self._update_project(project)
            self.glossary_session.updated(glossary)
            flushed = self.backend.flush()
            if (flushed and not had_edits and not repository.pending and repository.remote
                    and repository.remote["revision"] != base_revision
                    and self.backend.editor is editor and editor.revision == revision):
                selected = self.backend.current.get('id', '')
                restored = self._document(wire)
                repository.adopt_remote()
                self._applying = True
                self.backend.editor = type(editor)(restored)
                self.backend.editor.project_mode = True
                self.backend.editor.validator = self.validate_edit
                self.backend._current = next((i for i, c in enumerate(restored.cues) if c.id == selected), min(self.backend.currentIndex, len(restored.cues) - 1))
                self.backend.selection = {self.backend._current} if self.backend._current >= 0 else set()
                self._last_snapshot = restored.to_dict()
                self.backend._refresh()
                self._applying = False
            self.reviews.updated(reviews)
        self._run(operation, done)

    @Slot()
    def retry(self):
        self._blocked = False
        self.sync()

    @Slot(str, str)
    def workflow(self, action, reason=""):
        if not self.active or self._busy:
            return
        if not self.backend.flush() or not self.checkpoint():
            return
        if self.reviews.pending:
            self.backend.show_error("Дождитесь отправки сохранённого замечания или ответа")
            self.reviews.refresh()
            return
        if self.pending:
            self.backend.show_error("Дождитесь подтверждения всех правок сервером и повторите действие")
            self.sync()
            return
        self._error, self._status = "", "Изменение статуса…"
        self._run(lambda: self.repository.workflow(action, reason),
                  lambda state: self._workflow_done(action, state))

    def _workflow_done(self, action, state):
        self._episode_state = state
        self._status = {"submit_translation": "Перевод сдан", "start_review": "Редактура начата", "accept": "Ревизия утверждена"}.get(action, "Статус обновлён")
        self._blocked = action in ("submit_translation", "accept", "return")
        self._error = ""
        self.backend.notify(self._status)
        self.workflowCompleted.emit(action)

    @Slot()
    def resume(self):
        if self.active or self.busy or not self.backend._confirm_unsaved():
            return
        try:
            context = json.loads((self.backend.data_dir / "online-last.json").read_text(encoding="utf-8"))
            self.connect(context, resume=True)
        except (ValueError, OSError, KeyError) as exc:
            self.backend.show_error(str(exc))

    def disconnect(self):
        if self._applying:
            return
        self.timer.stop()
        self.reviews.saveDraftRequested.emit()
        self._generation += 1
        self.reviews.attach(None)
        self.glossary_session.attach(None)
        repository, self.repository = self.repository, None
        if repository:
            # Close in the same ordered worker, away from the UI thread.
            self._executor.submit(repository.close)
        self.conflicts.update()
        self.context = {}
        self._project_state, self._episode_state = {}, {}
        self._blocked, self._error = False, ""
        self.changed.emit()

    def request_close(self):
        """A close is accepted only after the latest durable draft is acknowledged."""
        self._close_timer_was_active |= self.timer.isActive()
        self.timer.stop()
        if self._allow_local_close:
            return True
        self._close_requested = True
        return self._continue_close()

    def _continue_close(self, *, error=None):
        if self._busy:
            return False  # _finished resumes after the existing worker/callback.
        if not self.backend.flush() or not self.checkpoint():
            self.cancel_close()
            return False
        if not self.pending:
            return True
        if error or self._blocked:
            message = error or self.status
            self._close_requested = False
            # Never open a modal dialog recursively inside QML's onClosing.
            QTimer.singleShot(0, lambda: self._confirm_close_failure(message))
            return False
        # sync confirms one immutable operation. An older in-flight operation
        # may leave a newer draft, so _finished repeats until that is sent too.
        self.sync()
        return False

    def _confirm_close_failure(self, message):
        if not self._closing and self.active:
            self.backend.confirm_online_close(message)

    def retry_close(self):
        if self.request_close():
            self.closeReady.emit()

    def cancel_close(self):
        self._close_requested = False
        self._allow_local_close = False
        if self._close_timer_was_active and self.active and not self._closing:
            self.timer.start()
        self._close_timer_was_active = False

    def close_locally(self):
        # The opt-in offline path still must save the latest field before exit.
        if self._busy or not self.backend.flush() or not self.checkpoint():
            self.cancel_close()
            return
        self._allow_local_close = True
        self.closeReady.emit()

    def shutdown(self):
        if self._closing:
            return
        # Also protect direct teardown paths after the QML tree is disposed.
        if self.active and self.backend.flush():
            self.checkpoint()
        self.timer.stop()
        self.reviews.saveDraftRequested.emit()
        self._closing = True
        self._generation += 1
        repository = self.repository
        if repository:
            self._executor.submit(repository.close)
        self._executor.shutdown(wait=False)
