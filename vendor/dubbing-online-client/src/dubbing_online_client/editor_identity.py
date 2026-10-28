"""Permanent editor identity, separate from a temporary local SSH listener."""

import hashlib
import json

from .api import normalize_server_url


def server_identity(url, ssh=None):
    if not ssh:
        return normalize_server_url(url)
    address = [str(ssh["host"]).lower(), ssh.get("ssh_port", 22), ssh.get("api_port", 8000)]
    return "ssh:" + hashlib.sha256(json.dumps(address).encode()).hexdigest()
