import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from copy import deepcopy
import time

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from substance.backend import Backend
from substance.repositories import remote_document, online_client

online_client()
from dubbing_online_client.documents import from_lines
from dubbing_online_client.repository import RemoteDocumentRepository


class Client:
    url = "https://example.test"
    def __init__(self):
        self.wire, _, _ = from_lines([{"text": "Hello", "s": 0, "e": 2}])
        self.wire["cues"][0]["translation"] = ""
        self.wire["extras"]["unknown"] = {"keep": True}
        self.wire["cues"][0]["extras"]["future"] = "preserved"
        self.revision = 1
    def request(self, method, path, body=None):
        if path == "/v1/projects/project":
            return {"roles": ["admin"], "episodes": []}
        assert not path.endswith("/lease"), "Substance must not reserve a series"
        if method == "PUT":
            self.wire = deepcopy(body["document"])
            self.revision += 1
        return {"project_id": "project", "episode_id": "episode", "revision": self.revision, "document": deepcopy(self.wire)}


@pytest.fixture
def backend(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    bridge = Backend()
    client = Client()
    repository = RemoteDocumentRepository(client, "user", "project", "episode", tmp_path / "online")
    repository.open()
    document = bridge.online._document(repository.snapshot)
    bridge._set_document(document, "")
    bridge.online.repository = repository
    bridge.online.context = {"episode_name": "Test series", "project_id": "project", "episode_id": "episode"}
    bridge.online._last_snapshot = document.to_dict()
    bridge.editor.project_mode = True
    bridge.editor.validator = bridge.online.validate_edit
    yield bridge
    bridge.online.disconnect()
    bridge.online._executor.submit(lambda: None).result(timeout=3)
    bridge.shutdown()


def wait(bridge):
    deadline = time.monotonic() + 3
    while bridge.online.busy and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not bridge.online.busy


def test_ack_preserves_undo_selection_and_unknown_fields(backend):
    repo = backend.online.repository
    source = deepcopy(repo.snapshot["source_lines"])
    backend.select(0, 0)
    backend.stage("text", "Привет")
    assert backend.flush()
    backend.online.sync()
    wait(backend)
    assert not backend.online.pending
    assert backend.currentIndex == 0 and backend.canUndo
    assert repo.snapshot["extras"]["unknown"] == {"keep": True}
    assert repo.snapshot["cues"][0]["extras"]["future"] == "preserved"
    assert repo.snapshot["source_lines"] == source
    backend.undo()
    assert backend.online.pending and backend.editor.document.cues[0].translation == ""
    backend.online.sync()
    wait(backend)
    assert repo.revision == 3


def test_original_changes_and_new_source_roll_back_before_undo(backend):
    before = deepcopy(backend.editor.document)
    with pytest.raises(ValueError, match="Оригинал"):
        backend.editor.transact("Bad", lambda d: setattr(d.cues[0], "original", "Changed"))
    with pytest.raises(ValueError, match="исходник"):
        backend.editor.add()
    assert backend.editor.document == before
    assert not backend.editor.undo_stack and not backend.online.pending


def test_shared_cards_and_remarks_cannot_be_saved_as_episode_data(backend):
    from substance.project import CharacterCard, ReviewEntry
    with pytest.raises(ValueError, match="карточки"):
        backend.editor.transact("Card", lambda d: d.characters.append(CharacterCard("char", "Name")))
    with pytest.raises(ValueError, match="замечания"):
        backend.editor.transact("Review", lambda d: d.reviews.append(ReviewEntry("review", cue_ids=[d.cues[0].id], text="Note")))
    assert not backend.online.pending


def test_local_document_can_replace_remote_without_losing_its_journal(backend):
    from substance.document import Document
    backend.stage("text", "Черновик")
    assert backend.flush()
    path = backend.online.repository.path
    backend._set_document(Document(), "")
    assert not backend.online.active and not backend.isProject
    assert path.exists() and "Черновик" in path.read_text()


@pytest.mark.parametrize("video_state", ["present", "missing", "unset"])
def test_handoff_video_is_local_and_survives_refresh_and_resume(
    backend, tmp_path, monkeypatch, video_state
):
    import json
    import dubbing_online_client
    import dubbing_online_client.credentials as credentials

    backend.online.disconnect()
    backend.online._executor.submit(lambda: None).result(timeout=3)
    client = Client()
    original = client.request

    def request(method, path, body=None):
        if path == "/v1/auth/editor/exchange":
            return {"project_id": "project", "episode_id": "episode",
                    "access_token": "private-token", "user": {"id": "user"}}
        if path == "/v1/auth/me":
            return {"id": "user"}
        if path.endswith("/glossary"):
            return []
        return original(method, path, body)

    client.request = request
    client.negotiate = lambda: {"capabilities": [
        "editor_handoff", "document_cas_v1", "document_revisions"]}
    monkeypatch.setattr(dubbing_online_client, "ApiClient", lambda url: client)

    class Vault:
        def put(self, *args):
            return True
        def get(self, *args):
            return "private-token"

    monkeypatch.setattr(credentials, "SessionVault", Vault)
    opened, cleared = [], []
    monkeypatch.setattr(backend.media_controller, "open", opened.append)
    monkeypatch.setattr(backend.media_controller, "clear", lambda: cleared.append(True))
    launch = {"server_url": client.url, "project_id": "project", "episode_id": "episode",
              "episode_name": "Test", "code": "one-time-secret"}
    video = tmp_path / "Видео серии 1.mkv"
    if video_state != "unset":
        launch["media_path"] = str(video)
    if video_state == "present":
        video.touch()
    # An unrelated previously open document must not supply the new episode's video.
    backend.editor.document.media = {"path": "previous-episode.mp4"}
    backend.online.connect(launch)
    wait(backend)
    backend.online.timer.stop()
    assert backend.online.active and not backend.online._error, backend.online.status
    expected = {"path": str(video)} if video_state == "present" else {}
    assert backend.editor.document.media == expected
    assert opened == ([str(video)] if expected else [])
    assert bool(cleared) == (not expected)
    saved = json.loads((backend.data_dir / "online-last.json").read_text())
    assert saved.get("media_path", "") == launch.get("media_path", "")
    assert "one-time-secret" not in repr(saved) and "private-token" not in repr(saved)

    # A new server revision replaces the editor; the device video must survive.
    QTest.qWait(20)
    wait(backend)
    client.wire["cues"][0]["translation"] = "Remote change"
    client.revision += 1
    backend.online.sync()
    wait(backend)
    assert backend.editor.document.cues[0].translation == "Remote change"
    assert backend.editor.document.media == expected
    assert str(video) not in backend.online.repository.path.read_text()
    assert str(video) not in repr(client.wire)

    backend.online.disconnect()
    backend.online._executor.submit(lambda: None).result(timeout=3)
    backend.online.resume()
    wait(backend)
    backend.online.timer.stop()
    assert not backend.online._error, backend.online.status
    assert backend.editor.document.media == expected


def test_media_selected_in_substance_survives_remote_refresh(backend, tmp_path, monkeypatch):
    video = tmp_path / "Changed locally.mp4"
    video.touch()
    monkeypatch.setattr(backend.media_controller, "open", lambda path: None)
    backend.openMediaPath(str(video))
    assert backend.editor.document.media == {"path": str(video)}
    backend.online.sync()
    wait(backend)
    assert not backend.online.pending
    client = backend.online.repository.client
    client.wire["cues"][0]["translation"] = "Updated remotely"
    client.revision += 1
    backend.online.sync()
    wait(backend)
    assert backend.editor.document.cues[0].translation == "Updated remotely"
    assert backend.editor.document.media == {"path": str(video)}
    backend.stage("text", "Local edit")
    assert backend.flush()
    backend.undo()
    assert backend.editor.document.media == {"path": str(video)}
    assert str(video) not in repr(client.wire)
