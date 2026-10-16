import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtWidgets import QApplication
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from substance.ass_formatting import toggle_format, selection_state, style_states
from substance.document import Cue, Document, plain_text, load_document
from substance.backend import Backend
from substance import visuals  # register QML types


def test_selection_toggle_preserves_other_tags_and_restores_inherited_weight():
    text = r"{\b700\i1}one two three{\i0}"
    start = text.index("two")
    result = toggle_format(text, start, start + 3, "b")
    assert result["text"] == r"{\b700\i1}one {\b0}two{\b700} three{\i0}"
    assert not selection_state(result["text"], result["start"], result["end"])["b"]
    assert selection_state(result["text"], result["end"] + 7, result["end"] + 7)["b"]
    assert plain_text(result["text"]) == plain_text(text)


def test_mixed_selection_and_reset_do_not_cancel_applied_format():
    text = r"one{\i1}two{\rDefault\bord2}three"
    assert not selection_state(text, 0, len(text))["i"]
    result = toggle_format(text, 0, len(text), "i")
    assert r"{\rDefault\bord2\i1}" in result["text"]
    assert selection_state(result["text"], result["start"], result["end"])["i"]
    off = toggle_format(result["text"], result["start"], result["end"], "i")
    assert not selection_state(off["text"], off["start"], off["end"])["i"]
    assert plain_text(off["text"]) == plain_text(text)


def test_cursor_pair_preserves_following_text_and_unicode_positions():
    text = "😀ab"
    result = toggle_format(text, 2, 2, "u")
    assert result == {"text": "😀{\\u1}{\\u0}ab", "start": 7, "end": 7}
    assert selection_state(result["text"], 7, 7)["u"]
    assert not selection_state(result["text"], 13, 13)["u"]
    result = toggle_format(text, 0, 2, "s")
    assert result["text"] == "{\\s1}😀{\\s0}ab"
    assert result["end"] - result["start"] == 2


def test_partial_override_selection_does_not_break_commands():
    text = r"A{\i1\bord2}B"
    result = toggle_format(text, 4, 4, "b")
    assert r"{\i1\bord2}{\b1}{\b0}B" in result["text"]
    with pytest.raises(ValueError):
        toggle_format(text, 0, 1, "invalid")


@pytest.fixture
def editor_ui(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if QQuickStyle.name() != "Fusion":
        QQuickStyle.setStyle("Fusion")
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    b = Backend()
    doc = Document(cues=[Cue(text="Hello world", original="Hello world", translation="Hello world")])
    b._set_document(doc, "")
    b.setMode("translation")
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", b)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "substance/qml/Main.qml")))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    QTest.qWait(80)
    field = window.findChild(QObject, "subtitleEditor")
    try:
        yield app, b, window, field
        errors = [m for m in messages if any(x in m for x in ("TypeError", "ReferenceError", "Cannot assign", "Unable to assign", "Binding loop"))]
        assert not errors
    finally:
        shiboken6.delete(window)
        shiboken6.delete(engine)
        b.shutdown()
        qInstallMessageHandler(previous)


@pytest.mark.parametrize("formatted", [False, True])
def test_toolbar_edits_translation_undo_and_roundtrip(editor_ui, tmp_path, formatted):
    app, b, window, field = editor_ui
    b.setAssFormatted(formatted)
    def click(name):
        button = window.findChild(QObject, "assFormat_" + name)
        assert button is not None
        point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
        QTest.mouseClick(button.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
        QTest.qWait(40)
    for kind in ("b", "i", "u", "s"):
        field.forceActiveFocus()
        field.select(6, 11)
        click(kind)
        expected = "Hello {\\" + kind + "1}world"
        assert field.property("text") == expected
        assert b.editor.document.cues[0].translation == expected
        assert b.editor.document.cues[0].original == "Hello world"
        assert b.assFormatted
        assert window.findChild(QObject, "assFormat_" + kind).property("checked")
        click(kind)
        assert not selection_state(field.property("text"), field.property("selectionStart"), field.property("selectionEnd"))[kind]
        b.undo()
        assert field.property("text") == expected
        b.undo()
        assert field.property("text") == "Hello world"
    field.select(0, 5)
    click("i")
    output = tmp_path / "formatted.substance"
    assert b._save_path(str(output))
    saved = load_document(output)
    assert saved.cues[0].translation == r"{\i1}Hello{\i0} world"
    assert saved.cues[0].original == "Hello world"
    if os.environ.get("SUBSTANCE_FORMAT_SCREENSHOT"):
        window.grabWindow().save(os.environ["SUBSTANCE_FORMAT_SCREENSHOT"])


def test_keyboard_formatting_then_typing_at_cursor(editor_ui):
    app, b, window, field = editor_ui
    b.setAssFormatted(True)
    field.forceActiveFocus()
    field.setProperty("cursorPosition", 5)
    QTest.keyClick(window, Qt.Key.Key_B, Qt.KeyboardModifier.ControlModifier)
    QTest.qWait(40)
    assert field.property("text") == r"Hello{\b1}{\b0} world"
    QTest.keyClick(window, Qt.Key.Key_X)
    assert b.flush()
    assert b.editor.document.cues[0].translation == r"Hello{\b1}x{\b0} world"
    assert b.editor.document.cues[0].original == "Hello world"


def test_invalid_timing_prevents_formatting(editor_ui):
    app, b, window, field = editor_ui
    b.stage("start", "invalid")
    assert b.applyAssFormat("Hello world", 0, 5, "i") == {}
    assert b.editor.document.cues[0].translation == "Hello world"


def test_inherited_styles_and_named_reset_restore_outside_selection():
    styles = style_states(["[V4+ Styles]", "Format: Name, Bold, Italic, Underline, StrikeOut", "Style: Default,-1,-1,0,0", "Style: Plain,0,0,0,0"])
    base = styles["Default"]
    result = toggle_format("Hello world", 0, 5, "i", base, styles)
    assert result["text"] == r"{\i0}Hello{\i1} world"
    assert selection_state(result["text"], len(result["text"]), len(result["text"]), base, styles)["i"]
    text = r"{\rPlain}Hello world"
    start = text.index("Hello")
    result = toggle_format(text, start, start + 5, "i", base, styles)
    assert result["text"] == r"{\rPlain}{\i1}Hello{\i0} world"


def test_toolbar_and_editor_show_inherited_style(editor_ui):
    app, b, window, field = editor_ui
    b.setUseAssStyles(True)
    b.editor.document.skeleton = ["[V4+ Styles]", "Format: Name, Bold, Italic, Underline, StrikeOut", "Style: Default,-1,-1,0,0", "[Events]"]
    b.currentChanged.emit()
    b.changed.emit()
    b.setAssFormatted(True)
    QTest.qWait(40)
    field = window.findChild(QObject, "subtitleEditor")
    field.forceActiveFocus()
    field.select(0, 5)
    assert window.findChild(QObject, "assFormat_i").property("checked")
    highlighter = b._ass_highlighters[0]
    assert highlighter.document().firstBlock().layout().formats()[0].format.fontItalic()
    result = b.applyAssFormat("Hello world", 0, 5, "i")
    assert result["text"] == r"{\i0}Hello{\i1} world"
    assert b.editor.document.cues[0].translation == result["text"]


def test_disable_inherited_bold_for_entire_cue_does_not_restore_it_at_end():
    text = "улетают туда, куда нужно."
    result = toggle_format(text, 0, len(text), "b", {"b": 1, "i": 0, "u": 0, "s": 0})
    assert result["text"] == r"{\b0}" + text
    assert not selection_state(result["text"], result["start"], result["end"], {"b": 1, "i": 0, "u": 0, "s": 0})["b"]


def test_new_document_default_is_regular_weight():
    styles = style_states(Document().skeleton)
    assert styles["Default"] == {"b": 0, "i": 0, "u": 0, "s": 0}


def test_inherited_bold_toolbar_switches_to_visual_editing_and_undo(editor_ui):
    app, backend, window, field = editor_ui
    backend.setUseAssStyles(True)
    backend.editor.document.skeleton = ["[V4+ Styles]", "Format: Name, Bold, Italic, Underline, StrikeOut", "Style: Default,-1,0,0,0", "[Events]"]
    backend.currentChanged.emit()
    backend.changed.emit()
    backend.setAssFormatted(False)
    assert window.findChild(QObject, "assFormat_b").property("checked")
    field.forceActiveFocus()
    field.select(0, len(field.property("text")))
    button = window.findChild(QObject, "assFormat_b")
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    QTest.mouseClick(button.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(40)
    assert backend.assFormatted
    assert field.property("text") == r"{\b0}Hello world"
    assert not button.property("checked")
    formats = backend._ass_highlighters[0].document().firstBlock().layout().formats()
    assert any(f.format.fontPointSize() == .1 for f in formats)
    assert all(not f.format.font().bold() for f in formats)
    assert backend.editor.document.cues[0].original == "Hello world"
    backend.undo()
    assert field.property("text") == "Hello world"
    assert button.property("checked")


def test_ass_style_preference_defaults_off_and_keeps_inline_formatting(editor_ui):
    from copy import deepcopy
    app, backend, window, field = editor_ui
    backend.editor.document.skeleton = ["[V4+ Styles]", "Format: Name, Bold, Italic, Underline, StrikeOut", "Style: Default,-1,-1,-1,-1", "[Events]"]
    backend.currentChanged.emit()
    backend.changed.emit()
    backend.setAssFormatted(True)
    before = deepcopy(backend.editor.document.to_dict())
    field.select(0, 5)
    assert not backend.useAssStyles
    assert not any(backend.assFormattingState("Hello world", 0, 5).values())
    assert not window.findChild(QObject, "useAssStylesMenuItem").property("checked")
    assert not window.findChild(QObject, "assFormat_b").property("checked")
    backend.setUseAssStyles(True)
    assert window.findChild(QObject, "useAssStylesMenuItem").property("checked")
    assert window.findChild(QObject, "assFormat_b").property("checked")
    assert window.findChild(QObject, "assFormat_i").property("checked")
    assert field.property("selectionStart") == 0 and field.property("selectionEnd") == 5
    backend.setUseAssStyles(False)
    assert not window.findChild(QObject, "assFormat_b").property("checked")
    assert backend.editor.document.to_dict() == before and not backend.draft
    for enabled in (False, True):
        backend.setUseAssStyles(enabled)
        state = backend.assFormattingState(r"{\b1}Bold{\b0}", 5, 9)
        assert state["b"]
    backend.settings.sync()
    restored = Backend()
    try:
        assert restored.useAssStyles
    finally:
        restored.shutdown()


def test_neutral_style_output_preserves_inline_commands_and_original_project(tmp_path):
    from copy import deepcopy
    from substance.document import parse_ass, export_document, save_document
    text = "[V4+ Styles]\nFormat: Name, Fontname, Bold, Italic, Underline, StrikeOut, Fontsize\nStyle: Default,Arial,-1,-1,-1,-1,48\nStyle: Other,Georgia,-1,0,0,0,30\n[Events]\nFormat: Start, End, Style, Text\nDialogue: 0:00:00.00,0:00:02.00,Default,{\\i1}Text{\\i0}\n"
    doc = parse_ass(text)
    before = deepcopy(doc.to_dict())
    assert doc.ass_text() == text
    neutral = doc.ass_text(use_ass_styles=False)
    assert "Style: Default,Arial,0,0,0,0,48" in neutral
    assert "Style: Other,Georgia,0,0,0,0,30" in neutral
    assert r"{\i1}Text{\i0}" in neutral
    assert doc.to_dict() == before
    path = tmp_path / "neutral.ass"
    save_document(doc, path, use_ass_styles=False)
    assert path.read_text(encoding="utf-8") == neutral
    restored = load_document(path).to_dict()
    restored.pop("ass_sha256", None)
    assert restored == before
    export_document(doc, path, use_ass_styles=False, originals=True)
    assert path.read_text(encoding="utf-8") == text
    project = tmp_path / "styles.substance"
    save_document(doc, project, use_ass_styles=False)
    assert load_document(project).skeleton == doc.skeleton


def test_backend_style_policy_matches_preview_save_and_export(editor_ui, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from substance.document import parse_ass
    app, backend, window, field = editor_ui
    backend.editor.document.skeleton = ["[V4+ Styles]", "Format: Name, Bold, Italic, Underline, StrikeOut", "Style: Default,-1,-1,0,0", "[Events]"]
    backend._update_preview()
    assert "Style: Default,0,0,0,0" in backend.previewScript
    output = tmp_path / "policy.ass"
    assert backend._save_path(str(output))
    assert style_states(parse_ass(output.read_text(encoding="utf-8")).skeleton)["Default"]["b"] == 0
    backend._ass_notice.close()
    backend.setUseAssStyles(True)
    backend._update_preview()
    assert "Style: Default,-1,-1,0,0" in backend.previewScript
    assert backend.save()
    assert style_states(parse_ass(output.read_text(encoding="utf-8")).skeleton)["Default"]["b"] == 1
    backend._ass_notice.close()
    assert backend._save_path(str(tmp_path / "policy.substance"))
    backend.setUseAssStyles(False)
    exported = tmp_path / "export.ass"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a: (str(exported), "ASS (*.ass)"))
    assert backend.saveAs()
    assert style_states(parse_ass(exported.read_text(encoding="utf-8")).skeleton)["Default"]["b"] == 0
    backend._ass_notice.close()
    backend.exportDialog()
    assert style_states(parse_ass(exported.read_text(encoding="utf-8")).skeleton)["Default"]["b"] == 0
    backend._ass_notice.close()
