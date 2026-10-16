"""Durable project actions and scoped, explicitly resumable media transfer."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
from urllib import request, error
from uuid import uuid4

from .api import ApiError, Cancelled
from .repository import atomic_json


class ProjectOutbox:
    """One immutable operation per account/project, including across processes."""

    def __init__(self, client, account_id, project_id, directory):
        self.client = client
        self.context = [client.url, account_id, project_id]
        self.base = f"/v1/projects/{project_id}"
        self.path = (
            Path(directory)
            / hashlib.sha256(json.dumps(self.context).encode()).hexdigest()
            / "project-actions.json"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock = None
        self.state = {
            "version": 1,
            "context": self.context,
            "pending": None,
            "rejected": False,
        }
        self._acquire()
        try:
            if self.path.exists():
                self.state = json.loads(self.path.read_text())
                if (
                    self.state.get("version") != 1
                    or self.state.get("context") != self.context
                ):
                    raise ValueError("Повреждён журнал проектных действий")
            self._validate(self.state.get("pending"))
        except BaseException:
            self.close()
            raise

    def _acquire(self):
        self.lock = self.path.with_suffix(".lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                self.lock.write(b"0")
                self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.lock.close()
            self.lock = None
            raise ValueError(
                "Действия этого онлайн-проекта уже открыты в другом процессе"
            ) from None

    def _validate(self, op):
        if op is None:
            return
        if (
            op.get("method") not in ("POST", "PUT")
            or not op.get("path", "").startswith(self.base + "/")
            or ".." in op["path"]
            or "?" in op["path"]
        ):
            raise ValueError("Некорректное проектное действие")
        from uuid import UUID

        UUID(op["body"]["operation_id"])

    def persist(self, state):
        atomic_json(self.path, state)
        self.state = state

    def enqueue(self, method, path, body, base=None):
        if self.state["pending"]:
            raise ValueError(
                "Сначала подтвердите предыдущее действие или верните отклонённое в черновик"
            )
        operation = {
            "method": method,
            "path": path,
            "body": {**deepcopy(body), "operation_id": str(uuid4())},
            "base": deepcopy(base),
        }
        self._validate(operation)
        self.persist({**self.state, "pending": operation, "rejected": False})

    def send(self):
        op = self.state["pending"]
        if not op:
            return None
        try:
            result = self.client.request(op["method"], op["path"], op["body"])
        except ApiError as exc:
            if exc.status in (400, 403, 404, 409, 422):
                self.persist({**self.state, "rejected": True})
            raise
        self.persist({**self.state, "pending": None, "rejected": False})
        return result

    def restore_rejected(self):
        if not self.state["pending"] or not self.state["rejected"]:
            raise ValueError(
                "Результат неизвестен. Сначала повторите сохранённое действие"
            )
        result = deepcopy(self.state["pending"])
        atomic_json(self.path.with_name("recovery-" + str(uuid4()) + ".json"), result)
        self.persist({**self.state, "pending": None, "rejected": False})
        return result

    def close(self):
        if self.lock:
            self.lock.close()
            self.lock = None


class MediaTransfer:
    def __init__(self, client, account_id, project_id, directory):
        self.client, self.project_id = client, project_id
        self.context = [client.url, account_id, project_id]
        self.directory = (
            Path(directory)
            / hashlib.sha256(json.dumps(self.context).encode()).hexdigest()
        )
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.base = f"/v1/projects/{project_id}/media"

    def upload(self, *args, **kwargs):
        lock = ProjectOutbox(
            self.client, self.context[1], self.project_id, self.directory / "locks"
        )
        try:
            return self._upload(*args, **kwargs)
        finally:
            lock.close()

    def download(self, *args, **kwargs):
        lock = ProjectOutbox(
            self.client, self.context[1], self.project_id, self.directory / "locks"
        )
        try:
            return self._download(*args, **kwargs)
        finally:
            lock.close()

    def _upload(
        self, path, kind, episode_id=None, base_version=0, offset_ms=0, progress=None
    ):
        path = Path(path)
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                if self.client.cancel and self.client.cancel.is_set():
                    raise Cancelled()
                digest.update(chunk)
        sha = digest.hexdigest()
        key = hashlib.sha256(
            json.dumps([sha, kind, episode_id, base_version, offset_ms]).encode()
        ).hexdigest()
        journal = self.directory / ("upload-" + key + ".json")
        body = {
            "operation_id": str(uuid4()),
            "kind": kind,
            "episode_id": episode_id,
            "name": path.name,
            "size": path.stat().st_size,
            "sha256": sha,
            "base_version": base_version,
            "offset_ms": offset_ms,
        }
        # Reuse an unacknowledged completed upload even if a refresh now reports
        # its published version. A lost completion response must not add a version.
        for candidate in sorted(self.directory.glob("upload-*.json")):
            saved = json.loads(candidate.read_text())
            if all(
                saved.get(k) == body[k]
                for k in ("kind", "episode_id", "sha256", "offset_ms", "size")
            ):
                journal = candidate
                break
        if journal.exists():
            body = json.loads(journal.read_text())
        else:
            atomic_json(journal, body)
        result = self.client.request("POST", self.base + "/uploads", body)
        upload = self.base + "/uploads/" + result["upload_id"]
        offset = result["offset"]
        with path.open("rb") as stream:
            stream.seek(offset)
            while offset < body["size"]:
                chunk = stream.read(min(4 * 1024 * 1024, body["size"] - offset))
                if not chunk:
                    raise ValueError("Файл изменился во время загрузки")
                result = self.client.request(
                    "PUT", upload, chunk, query={"offset": offset}, binary=True
                )
                offset = result["offset"]
                if progress:
                    progress(offset, body["size"])
        result = self.client.request("POST", upload + "/complete")
        journal.unlink(missing_ok=True)
        return result

    def _download(self, media, destination, progress=None):
        if not re.fullmatch(r"media_[a-f0-9]{32}", media["id"]) or not re.fullmatch(
            r"[a-f0-9]{64}", media["sha256"]
        ):
            raise ValueError("Некорректный ресурс")
        path = self.directory / (media["sha256"] + ".part")
        offset = path.stat().st_size if path.exists() else 0
        if offset > media["size"]:
            path.unlink()
            offset = 0
        headers = {"Authorization": "Bearer " + self.client.token}
        if offset:
            headers.update(
                Range=f"bytes={offset}-", **{"If-Range": '"' + media["sha256"] + '"'}
            )
        if offset < media["size"]:
            req = request.Request(
                self.client.url + self.base + "/" + media["id"] + "/download",
                headers=headers,
            )
            try:
                with self.client.opener.open(
                    req, timeout=self.client.timeout
                ) as response:
                    if response.status == 200:
                        offset = 0
                    elif response.status != 206 or not response.headers.get(
                        "Content-Range", ""
                    ).startswith(f"bytes {offset}-"):
                        raise ApiError("invalid_response")
                    with path.open("ab" if offset else "wb") as stream:
                        while chunk := response.read(1024 * 1024):
                            if self.client.cancel and self.client.cancel.is_set():
                                raise Cancelled()
                            offset += len(chunk)
                            if offset > media["size"]:
                                raise ApiError("invalid_response")
                            stream.write(chunk)
                            if progress:
                                progress(offset, media["size"])
                        stream.flush()
                        os.fsync(stream.fileno())
            except error.HTTPError as exc:
                raise ApiError("media_not_found", exc.code) from None
            except (error.URLError, TimeoutError):
                raise ApiError("network_error") from None
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        if offset != media["size"] or digest.hexdigest() != media["sha256"]:
            path.unlink(missing_ok=True)
            raise ApiError("media_integrity_failed")
        # Copy to a sibling temporary path so export works across filesystems atomically.
        import shutil
        import tempfile

        destination = Path(destination)
        fd, temporary = tempfile.mkstemp(prefix=".media-", dir=destination.parent)
        os.close(fd)
        try:
            shutil.copyfile(path, temporary)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        path.unlink(missing_ok=True)
        return str(destination)
