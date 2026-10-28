from copy import deepcopy
import json

from test_online import backend, Client
from dubbing_online_client.editor_identity import server_identity


class Vault:
    def __init__(self):
        self.tokens, self.secrets = {}, {}
    def put(self, identity, account, token):
        self.tokens[identity, account] = token
        return True
    def get(self, identity, account):
        return self.tokens.get((identity, account), "")
    def put_transport(self, identity, account, secret):
        self.secrets[identity, account] = dict(secret)
        return True


class Transport:
    def __init__(self, port):
        self.url = f"http://127.0.0.1:{port}"
        self.secret = {"password": "private-password"}
        self.closed = False
    def close(self):
        self.closed = True


def test_ssh_resume_renews_transport_but_reuses_journal_and_vault_identity(backend, monkeypatch):
    import dubbing_online_client
    # Release the fixture's unrelated journal before this independent session.
    backend.online.repository.close()
    backend.online.repository = None
    clients = []
    class API(Client):
        def __init__(self, url):
            super().__init__()
            self.url, self.token = url, ""
            clients.append(self)
        def negotiate(self):
            return {"capabilities": ["editor_handoff", "document_cas_v1", "document_revisions"]}
        def request(self, method, path, body=None):
            if path == "/v1/auth/editor/exchange":
                return {"project_id": "project", "episode_id": "episode", "access_token": "vault-token", "user": {"id": "user"}}
            if path == "/v1/auth/me":
                return {"id": "user"}
            if path.endswith("/glossary"):
                return []
            return super().request(method, path, body)
    monkeypatch.setattr(dubbing_online_client, "ApiClient", API)
    vault = Vault()
    launch = {"server_url": "http://127.0.0.1:8000", "project_id": "project", "episode_id": "episode", "episode_name": "One", "code": "one-use",
              "ssh": {"host": "server.test", "ssh_user": "user", "api_port": 8000}, "ssh_directory": str(backend.data_dir)}
    identity = server_identity(launch["server_url"], launch["ssh"])
    first_transport = Transport(41001)
    first = backend.online._connect_repository(launch, False, identity, vault, first_transport)
    document = first["repository"].snapshot
    document["cues"][0]["translation"] = "Draft before exit"
    first["repository"].checkpoint(document)
    old_path = first["repository"].path
    first["repository"].close()
    assert first_transport.closed
    context = json.loads((backend.data_dir / "online-last.json").read_text())
    assert "private-password" not in json.dumps(context)
    assert "41001" not in json.dumps(context)
    assert context["server_identity"] == identity
    second_transport = Transport(41002)
    resumed = backend.online._connect_repository(context, True, identity, vault, second_transport)
    try:
        assert resumed["repository"].path == old_path
        assert resumed["repository"].snapshot["cues"][0]["translation"] == "Draft before exit"
        assert clients[-1].token == "vault-token"
        assert list(vault.tokens) == [(identity, "user")]
    finally:
        resumed["repository"].close()


def test_ambiguous_legacy_drafts_have_a_native_choice_before_handoff(backend, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    from dubbing_online_client.repository import RemoteDocumentRepository
    paths = []
    for index in range(2):
        client = Client()
        client.url = f"http://127.0.0.1:{42000 + index}"
        repo = RemoteDocumentRepository(client, "user", "project", "episode", backend.data_dir / "online")
        repo.open()
        document = repo.snapshot
        document["cues"][0]["translation"] = f"Old draft {index}"
        repo.checkpoint(document)
        paths.append(repo.path)
        repo.close()
    launch = {"server_url": "http://127.0.0.1:8000", "project_id": "project", "episode_id": "episode",
              "account_id": "user", "ssh": {"host": "server.test"}}
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: (args[3][1], True))
    selected = backend.online._choose_legacy(launch)
    assert selected["legacy_journal"] in {str(path) for path in paths}
    assert all(path.exists() for path in paths)
    monkeypatch.setattr(QInputDialog, "getItem", lambda *args: ("", False))
    assert backend.online._choose_legacy(launch) is None
