"""Document repositories share one model; local saves retain existing IO."""
from .document import load_document, save_document


class LocalDocumentRepository:
    def load(self, path):
        return load_document(path)

    def save(self, document, path, *, use_ass_styles=True):
        save_document(document, path, use_ass_styles=use_ass_styles)


def online_client():
    # Source checkouts use the shared sibling package. Installed builds use its
    # declared wheel dependency; no server or DubbingManager UI is imported.
    try:
        import dubbing_online_client
    except ModuleNotFoundError:
        from pathlib import Path
        import sys
        source = Path(__file__).resolve().parents[2] / "DubbingManager/online/client/src"
        if not (source / "dubbing_online_client").is_dir():
            raise RuntimeError("Установите общий пакет dubbing-online-client") from None
        sys.path.insert(0, str(source))
        import dubbing_online_client
    return dubbing_online_client


def remote_document(snapshot, baseline):
    """Overlay editable fields, preserving server extras and immutable sources."""
    online_client()
    from copy import deepcopy
    from dubbing_online_client.documents import authored_document, from_substance, STAMP
    wire, _, _ = from_substance(snapshot)
    authoring = baseline.get("metadata", {}).get("authoring") is True
    if authoring:
        wire = authored_document(wire, baseline)
    if not authoring and any(sid not in baseline["source_lines"] for sid in wire["source_lines"]):
        raise ValueError("В онлайн-серии нельзя добавлять новый исходник. Разделяйте существующие реплики.")
    if not authoring:
        wire["source_lines"] = deepcopy(baseline["source_lines"])
    old = {c["id"]: c for c in baseline["cues"]}
    for cue in wire["cues"]:
        if cue["id"] in old:
            previous = old[cue["id"]]
            if cue["original"] != previous["original"]:
                raise ValueError("Оригинал онлайн-серии неизменяем")
            cue["extras"] = {**deepcopy(previous.get("extras", {})), **cue["extras"]}
    wire["extras"] = {**deepcopy(baseline.get("extras", {})), **wire["extras"]}
    # Shared remarks use their own API and journal. Preserve imported opaque
    # local review data without publishing it as a shared discussion.
    if STAMP in baseline.get("extras", {}):
        wire["extras"][STAMP]["reviews"] = deepcopy(baseline["extras"][STAMP].get("reviews", []))
    return wire
