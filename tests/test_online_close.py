"""Last keystrokes must be acknowledged before an online window closes."""
from copy import deepcopy
import json
import threading
import time

from PySide6.QtTest import QTest
import pytest

from test_online import backend as backend
from dubbing_online_client import ApiError


PHRASE = "улетают туда, куда нужно."


def until(predicate):
    deadline = time.monotonic() + 5
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(10)
    assert predicate()


def prepare(backend, monkeypatch):
    backend.select(0, 0)
    ready, failures = [], []
    backend.online.closeReady.connect(lambda: ready.append(True))
    monkeypatch.setattr(backend, "confirm_online_close", failures.append)
    return backend.online.repository, ready, failures


def test_immediate_close_flushes_field_before_debounce_and_waits_for_server(backend, monkeypatch):
    repo, ready, failures = prepare(backend, monkeypatch)
    backend.stage("text", PHRASE)
    assert backend.draft and repo.client.revision == 1
    assert not backend.requestClose()
    assert not ready
    assert json.loads(repo.path.read_text())["draft"]["cues"][0]["translation"] == PHRASE
    until(lambda: ready)
    assert repo.client.wire["cues"][0]["translation"] == PHRASE
    assert not repo.pending and not failures
    assert backend.requestClose()


def test_close_during_older_put_sends_latest_draft_after_its_ack(backend, monkeypatch):
    repo, ready, failures = prepare(backend, monkeypatch)
    entered, release = threading.Event(), threading.Event()
    original = repo.client.request
    writes = []

    def delayed(method, path, body=None):
        if method == "PUT" and path.endswith("/document"):
            writes.append(deepcopy(body))
            if len(writes) == 1:
                entered.set()
                assert release.wait(5)
        return original(method, path, body)

    monkeypatch.setattr(repo.client, "request", delayed)
    backend.stage("text", "улетают туда, ку")
    backend.online.sync()
    try:
        assert entered.wait(3)
        backend.stage("text", PHRASE)
        assert not backend.requestClose()
        assert not ready
    finally:
        release.set()
    until(lambda: ready)
    assert len(writes) == 2 and writes[0]["operation_id"] != writes[1]["operation_id"]
    assert writes[1]["base_revision"] == 2
    assert repo.client.wire["cues"][0]["translation"] == PHRASE
    assert not repo.pending and not failures


def test_unknown_put_retries_same_uuid_then_sends_newer_close_draft(backend, monkeypatch):
    repo, ready, failures = prepare(backend, monkeypatch)
    original = repo.client.request
    entered, release = threading.Event(), threading.Event()
    cached, attempts = {}, []

    def lost(method, path, body=None):
        if method != "PUT" or not path.endswith("/document"):
            return original(method, path, body)
        attempts.append(deepcopy(body))
        key = body["operation_id"]
        if key in cached:
            return deepcopy(cached[key])
        result = original(method, path, body)
        cached[key] = deepcopy(result)
        if len(cached) == 1:
            entered.set()
            assert release.wait(5)
            raise ApiError("network_error")
        return result

    monkeypatch.setattr(repo.client, "request", lost)
    backend.stage("text", "улетают туда, ку")
    backend.online.sync()
    try:
        assert entered.wait(3)
        backend.stage("text", PHRASE)
        assert not backend.requestClose()
    finally:
        release.set()
    until(lambda: failures)
    assert not ready and repo.pending
    pending = deepcopy(json.loads(repo.path.read_text())["pending"])
    backend.online.retry_close()
    until(lambda: ready)
    assert attempts[0] == attempts[1] == pending
    assert attempts[2]["operation_id"] != pending["operation_id"]
    assert repo.client.revision == 3
    assert repo.client.wire["cues"][0]["translation"] == PHRASE
    assert not repo.pending


@pytest.mark.parametrize("choice", ["cancel", "local"])
def test_network_failure_keeps_window_or_explicitly_closes_with_durable_draft(backend, monkeypatch, choice):
    repo, ready, failures = prepare(backend, monkeypatch)
    original = repo.client.request

    def offline(method, path, body=None):
        if method == "PUT" and path.endswith("/document"):
            raise ApiError("network_error")
        return original(method, path, body)

    monkeypatch.setattr(repo.client, "request", offline)
    backend.online.timer.start()
    backend.stage("text", PHRASE)
    assert not backend.requestClose()
    until(lambda: failures)
    assert not ready and repo.pending and repo.client.revision == 1
    if choice == "cancel":
        backend.online.cancel_close()
        assert backend.online.timer.isActive()
        assert not ready
    else:
        # New input during the error dialog must also survive an offline exit.
        backend.stage("text", PHRASE + " Ещё.")
        backend.online.close_locally()
        assert ready and backend.requestClose()
    saved = json.loads(repo.path.read_text())
    assert saved["draft"]["cues"][0]["translation"].startswith(PHRASE)
    assert saved["pending"]["document"]["cues"][0]["translation"] == PHRASE


def test_metadata_failure_after_text_ack_does_not_prevent_safe_close(backend, monkeypatch):
    repo, ready, failures = prepare(backend, monkeypatch)
    original = repo.client.request

    def failed_metadata(method, path, body=None):
        if path == "/v1/projects/project":
            raise ApiError("network_error")
        return original(method, path, body)

    monkeypatch.setattr(repo.client, "request", failed_metadata)
    backend.stage("text", PHRASE)
    assert not backend.requestClose()
    until(lambda: ready)
    assert not repo.pending and not failures
    assert repo.client.wire["cues"][0]["translation"] == PHRASE


def test_disk_failure_never_accepts_close_or_sends_an_unpersisted_field(backend, monkeypatch):
    repo, ready, failures = prepare(backend, monkeypatch)
    messages = []
    monkeypatch.setattr(backend, "show_error", messages.append)

    def failed_checkpoint(document):
        raise OSError("disk full")

    monkeypatch.setattr(repo, "checkpoint", failed_checkpoint)
    backend.stage("text", PHRASE)
    assert not backend.requestClose()
    assert not ready and not backend.online.busy and repo.client.revision == 1
    assert backend.editor.document.cues[0].translation == PHRASE
    assert messages and not failures
