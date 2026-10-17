"""Writing from scratch uses working text and immutable empty source anchors."""
from copy import deepcopy

from substance.document import Document
from substance.editor import Editor
from substance.repositories import remote_document, online_client

online_client()
from dubbing_online_client.documents import from_lines, to_substance


def test_empty_online_series_can_author_save_again_and_undo():
    baseline, _, _ = from_lines([], {"authoring": True})
    baseline["extras"]["future"] = "preserved"
    editor = Editor(Document.from_dict(to_substance(baseline)))
    editor.validator = lambda document: remote_document(document.to_dict(), baseline)
    editor.add()
    editor.update(0, text="Создано на слух")
    wire = remote_document(editor.document.to_dict(), baseline)
    assert wire["cues"][0]["translation"] == "Создано на слух"
    assert wire["cues"][0]["original"] == ""
    assert all(source["text"] == "" for source in wire["source_lines"].values())
    assert wire["extras"]["future"] == "preserved"

    baseline = deepcopy(wire)
    editor.update(0, text="Правка после сохранения")
    wire = remote_document(editor.document.to_dict(), baseline)
    assert wire["cues"][0]["translation"] == "Правка после сохранения"
    assert wire["source_lines"] == baseline["source_lines"]
    editor.add(after=0)
    editor.update(1, text="Вторая реплика")
    wire = remote_document(editor.document.to_dict(), baseline)
    assert len(wire["cues"]) == len(wire["source_lines"]) == 2
    editor.undo()
    editor.redo()
    assert remote_document(editor.document.to_dict(), baseline) == wire
