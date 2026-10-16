"""Online submission and acceptance do not depend on cue completeness."""
from copy import deepcopy

import pytest

from test_online import backend as backend, wait


@pytest.mark.parametrize("text", ["", " \t "])
@pytest.mark.parametrize("action", ["submit_translation", "accept"])
def test_blank_rows_can_be_submitted_and_accepted(backend, monkeypatch, text, action):
    online = backend.online
    repository = online.repository
    backend.select(0, 0)
    backend.stage("text", text)
    assert backend.flush()
    online.sync()
    wait(backend)
    assert not online.pending

    kind = "translation" if action == "submit_translation" else "editing"
    online.context["account_id"] = "user"
    online._project_state = {"roles": ["translator" if kind == "translation" else "editor"]}
    online._episode_state = {
        "id": "episode", "revision": repository.revision,
        "translation_status": "in_progress" if kind == "translation" else "ready",
        "review_status": "pending" if kind == "translation" else "in_review",
        "tasks": {kind: "user"},
    }
    assert online.canSubmit if action == "submit_translation" else online.canAccept
    before = repository.snapshot
    assert before["cues"][0]["translation"] == text
    calls, errors = [], []
    monkeypatch.setattr(backend, "show_error", errors.append)

    def request(method, path, body=None):
        calls.append((method, path, deepcopy(body)))
        return online._episode_state | {
            "translation_status": "ready",
            "review_status": "pending" if action == "submit_translation" else "accepted",
            "submitted_revision": repository.revision,
            "accepted_revision": repository.revision if action == "accept" else None,
        }

    monkeypatch.setattr(repository.client, "request", request)
    online.workflow(action)
    wait(backend)
    assert not errors and not online._error
    assert calls == [("POST", repository.base + "/workflow", {
        "action": action, "revision": repository.revision, "reason": "",
    })]
    assert repository.snapshot == before
    assert not online.pending
    assert online._episode_state["translation_status"] == "ready"
    if action == "accept":
        assert online._episode_state["accepted_revision"] == repository.revision
