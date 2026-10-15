from copy import deepcopy
from uuid import uuid4

import pytest

from test_online import backend as backend, wait
from dubbing_online_client import ApiError
from dubbing_online_client.reviews import RemoteReviews


@pytest.fixture
def reviews(backend):
    online = backend.online
    online.context["account_id"] = "user"
    online._project_state = {"roles": ["admin"]}
    online._episode_state = {"accepted_revision": None}
    repo = online.repository
    original = repo.client.request
    rows, operations = [], {}

    def request(method, path, body=None, **kwargs):
        if "/reviews" not in path:
            return original(method, path, body)
        if method == "GET":
            return {
                "items": deepcopy(rows),
                "next": None,
                "permissions": {
                    "can_create": True,
                    "can_reply": True,
                    "can_decide": True,
                },
            }
        if body["operation_id"] in operations:
            return operations[body["operation_id"]]
        if path.endswith("/reviews"):
            row = {
                "id": "review_" + uuid4().hex,
                "cue_id": body["cue_id"],
                "revision": body["revision"],
                "kind": body["kind"],
                "text": body["text"],
                "state": "open",
                "version": 1,
                "created_at": "2026-10-14",
                "context": {},
                "messages": [],
            }
            rows.append(row)
        else:
            row = next(r for r in rows if r["id"] in path)
            if body["base_version"] != row["version"]:
                raise ApiError("review_version_conflict", 409)
            row["version"] += 1
            row["messages"].append({"version": row["version"], "text": body["text"]})
            if "state" in body:
                row["state"] = body["state"]
        operations[body["operation_id"]] = deepcopy(row)
        return deepcopy(row)

    repo.client.request = request
    remote = RemoteReviews(repo)
    remote.refresh()
    online.reviews.attach(remote)
    backend.select(0, 0)
    return online.reviews


def test_shared_review_does_not_change_text_revision_or_undo(backend, reviews):
    before = backend.editor.document.to_dict()
    assert reviews.create("note", "Замечание", "")
    wait(backend)
    assert len(reviews.entries) == 1 and not reviews.pending
    assert backend.editor.document.to_dict() == before
    assert backend.online.revision == 1 and not backend.online.pending
    assert not backend.canUndo
    assert backend.review_count(backend.current["id"], "note") == 1


def test_unknown_response_requires_exact_retry_not_new_draft(backend, reviews):
    client = backend.online.repository.client
    original = client.request
    lost = [True]

    def request(method, path, body=None, **kwargs):
        result = original(method, path, body, **kwargs)
        if method == "POST" and lost[0]:
            lost[0] = False
            raise ApiError("network_error")
        return result

    client.request = request
    assert reviews.create("note", "Note", "")
    wait(backend)
    assert reviews.pending and not reviews.canRestore
    assert not reviews.restorePending()
    pending = deepcopy(reviews.repository.state["pending"])
    reviews.retry()
    wait(backend)
    assert not reviews.pending and len(reviews.entries) == 1
    assert pending["body"]["text"] == "Note"


def test_conflict_preserves_pending_text_and_base_version(backend, reviews):
    assert reviews.create("note", "Note", "")
    wait(backend)
    row = reviews.entries[0]
    original = backend.online.repository.client.request

    def conflict(method, path, body=None, **kwargs):
        if method == "POST":
            raise ApiError("review_version_conflict", 409)
        return original(method, path, body, **kwargs)

    backend.online.repository.client.request = conflict
    assert reviews.respond(row["id"], "", "Ответ")
    wait(backend)
    assert reviews.pending and reviews.canRestore and not backend.online.blocked
    assert reviews.restorePending()
    assert reviews.draft["text"] == "Ответ" and reviews.draft["base_version"] == 1
    assert not backend.online.pending


def test_stale_composer_version_and_unconfirmed_document_are_rejected(backend, reviews):
    assert reviews.create("note", "Note", "")
    wait(backend)
    row = reviews.entries[0]
    assert not reviews.respondAt(row["id"], "", "Reply", row["version"] + 1)
    assert not reviews.createAt(
        "note", "Note", "", backend.current["id"], backend.online.revision + 1
    )
    backend.stage("text", "Unsent translation")
    backend.flush()
    assert not reviews.canCreate and not reviews.create("note", "Note", "")


def test_draft_survives_reconstruction_and_is_outside_document(backend, reviews):
    assert reviews.saveDraft({"text": "Черновик ответа", "base_version": 7})
    restored = RemoteReviews(backend.online.repository)
    assert restored.state["draft"]["text"] == "Черновик ответа"
    assert not backend.online.pending and not backend.editor.document.reviews


def test_discussions_refresh_after_submit_blocks_text_edits(backend, reviews):
    backend.online._blocked = True
    backend.online.sync()
    wait(backend)
    assert reviews.canReply and not backend.online.pending
