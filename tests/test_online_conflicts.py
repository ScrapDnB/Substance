from copy import deepcopy
from test_online import backend as backend, wait


def conflict(backend):
    backend.editor.update(0, translation="Mine")
    backend._refresh()
    client = backend.online.repository.client
    client.wire["cues"][0]["translation"] = "Server"
    client.wire["extras"]["unknown"]["new"] = "Keep"
    client.revision = 2
    backend.online.repository.refresh_remote()
    backend.online.conflicts.update()
    return backend.online.conflicts.comparison


def test_resolve_keeps_server_metadata_and_undo_only_reverts_own_text(backend):
    view = conflict(backend)
    selected = {row["key"]: "mine" for row in view["conflicts"]}
    assert backend.online.conflicts.resolve(view["token"], selected, "merge")
    assert backend.editor.document.cues[0].translation == "Mine"
    assert backend.online.repository.revision == 2
    assert backend.online.repository.snapshot["extras"]["unknown"]["new"] == "Keep"
    assert backend.canUndo
    backend.undo()
    assert backend.editor.document.cues[0].translation == "Server"
    assert backend.online.repository.snapshot["extras"]["unknown"]["new"] == "Keep"
    backend.redo()
    assert backend.editor.document.cues[0].translation == "Mine"
    assert list(backend.online.repository.path.parent.glob("recovery-*.json"))


def test_stale_comparison_and_disk_error_do_not_replace_ui_or_journal(
    backend, monkeypatch
):
    view = conflict(backend)
    backend.editor.update(0, translation="Typing after opening comparison")
    backend._refresh()
    assert not backend.online.conflicts.resolve(view["token"], {}, "server")
    assert (
        backend.editor.document.cues[0].translation == "Typing after opening comparison"
    )
    backend.online.conflicts.update()
    view = backend.online.conflicts.comparison
    before = deepcopy(backend.online.repository.snapshot)
    original = __import__(
        "dubbing_online_client.repository", fromlist=["atomic_json"]
    ).atomic_json

    def fail_journal(path, value):
        if path.name == "journal.json":
            raise OSError("Disk full")
        return original(path, value)

    monkeypatch.setattr("dubbing_online_client.repository.atomic_json", fail_journal)
    assert not backend.online.conflicts.resolve(view["token"], {}, "server")
    assert (
        backend.online.repository.snapshot == before
        and backend.online.repository.revision == 1
    )
    assert (
        backend.editor.document.cues[0].translation == "Typing after opening comparison"
    )


def test_blocked_clean_reader_updates_text_without_reopening(backend):
    backend.online._blocked = True
    client = backend.online.repository.client
    client.wire["cues"][0]["translation"] = "New server text"
    client.revision = 2
    backend.online.sync()
    wait(backend)
    assert backend.editor.document.cues[0].translation == "New server text"
    assert backend.online.revision == 2 and not backend.online.pending


def test_blocked_reader_keeps_local_draft_and_refreshes_comparison(backend):
    view = conflict(backend)
    backend.online._blocked = True
    backend.online.sync()
    wait(backend)
    assert backend.editor.document.cues[0].translation == "Mine"
    assert backend.online.revision == 1 and backend.online.conflicts.available
    assert backend.online.conflicts.comparison["token"] == view["token"]


def test_revoked_session_does_not_remove_a_renewed_credential(backend, monkeypatch):
    from dubbing_online_client import ApiError

    deleted = []

    class Vault:
        def get(self, *args):
            return "renewed-token"

        def delete(self, *args):
            deleted.append(args)

    monkeypatch.setattr("dubbing_online_client.credentials.SessionVault", Vault)
    backend.online.context.update(account_id="user", server_url="https://example.test")
    backend.online.repository.client.token = "old-token"

    def forbidden(*args):
        raise ApiError("invalid_session", 401)

    backend.online.repository.client.request = forbidden
    backend.online.sync()
    wait(backend)
    assert backend.online._blocked and not deleted


def test_typing_during_clean_refresh_does_not_use_unseen_server_base(backend):
    import threading
    client = backend.online.repository.client
    client.wire['cues'][0]['translation'] = 'New server text'
    client.revision = 2
    reached, release = threading.Event(), threading.Event()
    request = client.request
    def delayed(method, path, body=None):
        if path == '/v1/projects/project':
            reached.set()
            assert release.wait(3)
        return request(method, path, body)
    client.request = delayed
    backend.online.sync()
    try:
        assert reached.wait(3)
        # Leave the form staged: the response callback must flush it before
        # adopting a version the user never saw while typing.
        backend.stage('text', 'Typed against the old visible version')
        release.set()
        wait(backend)
        assert backend.editor.document.cues[0].translation == 'Typed against the old visible version'
        assert backend.online.repository.revision == 1
        assert backend.online.conflicts.available
        assert backend.online.repository.remote['document']['cues'][0]['translation'] == 'New server text'
    finally:
        release.set()
