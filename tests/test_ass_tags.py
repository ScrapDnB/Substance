import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from pathlib import Path
import pytest
from PySide6.QtCore import QObject, QUrl, QPointF, Qt, qInstallMessageHandler
from PySide6.QtGui import QTextDocument
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtWidgets import QApplication, QFileDialog
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
import shiboken6

from substance.ass_tags import inventory, remove_tags, remove_document_tags
from substance.ass_highlighter import AssHighlighter
from substance.document import parse_ass, save_document, load_document, Cue, Document
from substance.editor import Editor
from substance.backend import Backend
from substance import visuals  # register QML types


@pytest.fixture
def app():
    instance = QApplication.instance() or QApplication([])
    QQuickStyle.setStyle("Fusion")
    return instance


def test_nested_cleanup_preserves_unselected_commands_and_comments():
    text = r"{note}{\i1\bord2\t(0,500,\i0\blur3)}Hello{\i0}\Nworld"
    assert remove_tags(text, {"i"}) == r"{note}{\bord2\t(0,500,\blur3)}Hello\Nworld"
    assert remove_tags(text, {"i", "blur"}) == r"{note}{\bord2}Hello\Nworld"
    assert remove_tags(r"{}{\t(0,500,)}X", {"i"}) == r"{}{\t(0,500,)}X"
    assert remove_tags(text, {"t"}) == r"{note}{\i1\bord2}Hello{\i0}\Nworld"
    found = {t["name"]: (t["count"], t["lines"]) for t in inventory([text, r"{\i1}X"])}
    assert found["i"] == (4, 2)
    assert found["t"] == (1, 1)


def test_font_reset_and_color_prefixes_and_unknowns():
    text = r"{\fnArial\fs24\fscx110\rDefault\1c&HFF00FF&\xyz42}Text{unfinished"
    names = {t["name"] for t in inventory([text])}
    assert names == {"fn", "fs", "fscx", "r", "1c", "xyz"}
    assert remove_tags(text, {"fs", "r"}) == r"{\fnArial\fscx110\1c&HFF00FF&\xyz42}Text{unfinished"


def test_cleanup_one_transaction_source_preserved_and_roundtrip(tmp_path):
    doc = parse_ass("[Events]\nFormat: Start, End, Text\nDialogue: 0:00:00.00,0:00:02.00,{\\i1}Source{\\i0}\n")
    doc.cues[0].translation = r"{\b1}Перевод{\b0}{\i1}!"
    editor = Editor(doc)
    before = deepcopy(doc.to_dict())
    assert remove_document_tags(editor, {"b", "i"})
    assert editor.document.cues[0].translation == "Перевод!"
    assert editor.document.cues[0].original == doc.cues[0].original
    assert editor.document.source_lines == doc.source_lines
    assert len(editor.undo_stack) == 1
    path = tmp_path / "clean.substance"
    save_document(editor.document, path)
    assert load_document(path).cues[0].translation == "Перевод!"
    assert "{\\b1}" not in editor.document.ass_text()
    editor.undo()
    assert editor.document.to_dict() == before
    editor.redo()
    assert editor.document.cues[0].translation == "Перевод!"


def test_highlighter_keeps_raw_text_and_formats_after_emoji(app):
    doc = QTextDocument()
    raw = "😀{\\i1}курсив\nещё{\\i0} обычно"
    doc.setPlainText(raw)
    highlighter = AssHighlighter(doc, True)
    highlighter.rehighlight()
    assert doc.toPlainText() == raw
    first = doc.firstBlock().layout().formats()
    assert any(f.format.fontItalic() for f in first)
    assert any(f.format.fontPointSize() == .1 for f in first)
    assert any(f.format.fontItalic() for f in doc.firstBlock().next().layout().formats())
    highlighter.formatted = False
    highlighter.rehighlight()
    assert doc.toPlainText() == raw
    assert not any(f.format.fontItalic() for f in doc.firstBlock().layout().formats())


def test_editor_toggle_and_dialog_are_lossless(app, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    b = Backend()
    b._set_document(Document(cues=[Cue(text=r"{\i1}Hello{\i0}", original=r"{\i1}Hello{\i0}")]), "")
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", b)
    try:
        engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "substance/qml/Main.qml")))
        assert engine.rootObjects(), messages
        w = engine.rootObjects()[0]
        QTest.qWait(60)
        field = w.findChild(QObject, "subtitleEditor")
        raw = field.property("text")
        before = b.editor.document.to_dict()
        b.setAssFormatted(True)
        QTest.qWait(30)
        assert field.property("text") == raw
        assert b.editor.document.to_dict() == before and not b.dirty
        field.setProperty("text", raw + "!")
        assert b.flush()
        assert b.editor.document.cues[0].output_text == raw + "!"
        def js(code):
            exp = QQmlExpression(qmlContext(w), w, code)
            exp.evaluate()
            assert not exp.hasError(), exp.error().toString()
            QTest.qWait(30)
        js("assTagsDialog.open()")
        assert w.findChild(QObject, "assTagsList").property("count") == 1
        assert w.property("modalOpen")
        if os.environ.get("SUBSTANCE_ASS_SCREENSHOT"):
            w.findChild(QObject, "assTagsDialog").grabWindow().save(os.environ["SUBSTANCE_ASS_SCREENSHOT"])
        js("assTagsDialog.selected = ['i']")
        button = w.findChild(QObject, "removeAssTagsButton")
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(button.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(40)
        assert not w.findChild(QObject, "assTagsDialog").isVisible()
        assert b.editor.document.cues[0].output_text == "Hello!"
        b.undo()
        assert b.editor.document.cues[0].output_text == raw + "!"
        b.setAssFormatted(False)
        assert field.property("text") == raw + "!"
        assert not w.grabWindow().isNull()
        errors = [m for m in messages if any(x in m for x in ("TypeError", "ReferenceError", "Cannot assign", "Unable to assign", "Binding loop"))]
        assert not errors
    finally:
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        b.shutdown()
        qInstallMessageHandler(previous)


def test_ass_save_and_exports_warn_and_keep_original(app, tmp_path, monkeypatch):
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    b = Backend()
    b._set_document(Document(cues=[Cue(text="Source", original="Source", translation="Перевод")]), "")
    try:
        ass = tmp_path / "saved.ass"
        assert b._save_path(str(ass))
        assert b._ass_notice.isVisible()
        assert ".substance" in b._ass_notice.informativeText()
        assert "saved.ass.substance" in b._ass_notice.informativeText()
        assert load_document(ass).cues[0].original == "Source"
        assert "Перевод" in ass.read_text(encoding="utf-8")
        b._ass_notice.close()
        assert b.save()
        assert b._ass_notice.isVisible()
        b._ass_notice.close()
        assert b._save_path(str(tmp_path / "work.substance"))
        output = tmp_path / "export.ass"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(output), "ASS (*.ass)"))
        assert b.saveAs()
        assert b._ass_notice.isVisible()
        assert "Сохраните проект" in b._ass_notice.informativeText()
        b._ass_notice.close()
        b.exportDialog(True)
        assert b._ass_notice.isVisible()
        assert "оригинальный" in b._ass_notice.text()
        assert "Source" in output.read_text(encoding="utf-8")
    finally:
        if b._ass_notice:
            b._ass_notice.close()
        b.shutdown()


def test_cleanup_freezes_authored_source_and_ignores_missing_tags():
    editor = Editor()
    editor.add()
    editor.update(0, text=r"{\i1}Original{\i0}")
    before = deepcopy(editor.document.to_dict())
    assert not remove_document_tags(editor, {"bord"})
    assert editor.document.to_dict() == before
    assert remove_document_tags(editor, {"i"})
    assert editor.document.cues[0].text == "Original"
    assert editor.document.cues[0].original == before["cues"][0]["original"]
    assert editor.document.source_lines == before["source_lines"]
    editor.update(0, text="Later edit")
    assert editor.document.cues[0].original == before["cues"][0]["original"]
