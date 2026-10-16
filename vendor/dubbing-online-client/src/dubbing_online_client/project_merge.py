"""Three-way project state merge; lists are atomic and deletion is explicit."""

from copy import deepcopy

_MISSING = object()


def merge_project_state(base, mine, remote, choices=None):
    choices = choices or {}
    conflicts = []

    def walk(before, local, server, path):
        if local == before or local == server:
            return deepcopy(server) if server is not _MISSING else _MISSING
        if server == before:
            return deepcopy(local) if local is not _MISSING else _MISSING
        if all(isinstance(v, dict) for v in (before, local, server)):
            result = {}
            for key in sorted(set(before) | set(local) | set(server)):
                value = walk(
                    before.get(key, _MISSING),
                    local.get(key, _MISSING),
                    server.get(key, _MISSING),
                    path + [key],
                )
                if value is not _MISSING:
                    result[key] = value
            return result
        name = "/".join(path)
        if choices.get(name) in ("mine", "server"):
            value = local if choices[name] == "mine" else server
            return deepcopy(value) if value is not _MISSING else _MISSING
        conflicts.append(
            {
                "path": name,
                "base": None if before is _MISSING else deepcopy(before),
                "mine": None if local is _MISSING else deepcopy(local),
                "server": None if server is _MISSING else deepcopy(server),
            }
        )
        return deepcopy(server) if server is not _MISSING else _MISSING

    result = walk(base, mine, remote, [])
    return result, conflicts
