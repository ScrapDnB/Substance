import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from copy import deepcopy
from pathlib import Path
import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, Qt, QUrl, qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from substance.ass_inheritance import inherit_formatting, whole_line_template
from substance.backend import Backend
from substance.document import Document, Cue, load_document
from substance import visuals  # register QML types


def test_whole_line_only_and_no_fragment_projection():
    assert whole_line_template(r"{\i1\c&H00FF00&}Whole line{\i0}") == (r"{\i1\c&H00FF00&}", r"{\i0}")
    for source in (r"A {\i1}fragment{\i0}", r"{\i1}A{\i0} fragment", r"{\b1}A {\i1}fragment{\i0}{\b0}"):
        assert whole_line_template(source) is None
        assert inherit_formatting(source, "Совсем другой текст")["text"] == "Совсем другой текст"
    assert whole_line_template(r"{\p1}m 0 0 l 10 10{\p0}") is None
    assert whole_line_template(r"{\k100}Karaoke") is None


def test_unicode_mapping_idempotence_and_manual_formatting():
    original = r"{\i1}Original{\i0}"
    result = inherit_formatting(original, "😀перевод", 2, 9, 9)
    assert result == {"text": "{\\i1}😀перевод{\\i0}", "start": 7, "end": 14, "cursor": 14}
    assert inherit_formatting(original, result["text"], 7, 14, 14) == result
    manual = r"Часть {\i1}перевода{\i0}"
    assert inherit_formatting(original, manual)["text"] == manual
    assert inherit_formatting(original, "")["text"] == ""
    assert inherit_formatting("No tags", "Текст")["text"] == "Текст"


@pytest.fixture
def translation_ui(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    if QQuickStyle.name() != "Fusion":
        QQuickStyle.setStyle("Fusion")
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    backend = Backend()
    backend._set_document(Document(cues=[
        Cue(text=r"{\i1}Original{\i0}", original=r"{\i1}Original{\i0}"),
        Cue(text=r"A {\b1}fragment{\b0}", original=r"A {\b1}fragment{\b0}"),
    ]), "")
    backend.setMode("translation")
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "substance/qml/Main.qml")))
    assert engine.rootObjects(), messages
    window = engine.rootObjects()[0]
    QTest.qWait(60)
    try:
        yield app, backend, window
        errors = [m for m in messages if any(x in m for x in ("TypeError", "ReferenceError", "Cannot assign", "Unable to assign", "Binding loop"))]
        assert not errors
    finally:
        shiboken6.delete(window)
        shiboken6.delete(engine)
        backend.shutdown()
        qInstallMessageHandler(previous)


def click(window, name):
    button = window.findChild(QObject, name)
    point = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
    QTest.mouseClick(button.window(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)
    QTest.qWait(30)


def test_source_and_translation_visualization_independent_and_persistent(translation_ui):
    app, backend, window = translation_ui
    before = deepcopy(backend.editor.document.to_dict())
    backend.setAssFormatted(False)
    backend.setAssOriginalFormatted(False)
    click(window, "originalAssFormattingToggle")
    assert backend.assOriginalFormatted and not backend.assFormatted
    edit, source = backend._ass_highlighters
    assert source.formatted and not edit.formatted
    assert any(f.format.fontItalic() for f in source.document().firstBlock().layout().formats())
    click(window, "assFormattingToggle")
    assert backend.assOriginalFormatted and backend.assFormatted
    click(window, "originalAssFormattingToggle")
    assert not backend.assOriginalFormatted and backend.assFormatted
    assert backend.editor.document.to_dict() == before and not backend.dirty
    backend.settings.sync()
    restored = Backend()
    try:
        assert not restored.assOriginalFormatted and restored.assFormatted
    finally:
        restored.shutdown()


def test_live_typing_inherits_only_whole_line_and_undo(translation_ui, tmp_path):
    app, backend, window = translation_ui
    backend.setPreserveAssFormatting(True)
    backend.setAssFormatted(True)
    assert window.findChild(QObject, "preserveAssFormattingMenuItem").property("checked")
    field = window.findChild(QObject, "subtitleEditor")
    field.forceActiveFocus()
    for key in (Qt.Key.Key_A, Qt.Key.Key_B, Qt.Key.Key_C):
        QTest.keyClick(window, key)
        QTest.qWait(20)
    assert field.property("text") == r"{\i1}abc{\i0}"
    assert backend.flush()
    assert backend.editor.document.cues[0].translation == field.property("text")
    assert backend.editor.document.cues[0].original == r"{\i1}Original{\i0}"
    assert not backend.draft
    backend.undo()
    QTest.qWait(30)
    assert backend.editor.document.cues[0].translation is None
    assert field.property("text") == ""
    backend.redo()
    assert backend.editor.document.cues[0].translation == r"{\i1}abc{\i0}"
    backend.navigate(1)
    field = window.findChild(QObject, "subtitleEditor")
    field.setProperty("text", "Перевод фрагмента")
    QTest.qWait(30)
    assert backend.flush()
    assert backend.editor.document.cues[1].translation == "Перевод фрагмента"
    output = tmp_path / "inherit.substance"
    assert backend._save_path(str(output))
    saved = load_document(output)
    assert saved.cues[0].translation == r"{\i1}abc{\i0}"
    assert saved.cues[1].translation == "Перевод фрагмента"


def test_toggle_on_formats_current_translation_and_display_does_not_edit_it(translation_ui):
    app, backend, window = translation_ui
    field = window.findChild(QObject, "subtitleEditor")
    field.setProperty("text", "Перевод")
    assert backend.flush()
    backend.setPreserveAssFormatting(True)
    QTest.qWait(30)
    assert field.property("text") == r"{\i1}Перевод{\i0}"
    assert backend.flush()
    backend.undo()
    QTest.qWait(30)
    assert field.property("text") == "Перевод"
    before = deepcopy(backend.editor.document.to_dict())
    click(window, "originalAssFormattingToggle")
    click(window, "assFormattingToggle")
    assert backend.editor.document.to_dict() == before and not backend.draft
    backend.setPreserveAssFormatting(False)
    field.setProperty("text", "Другой перевод")
    QTest.qWait(30)
    assert backend.flush()
    assert backend.editor.document.cues[0].translation == "Другой перевод"


def test_flush_before_ui_callback_and_preserve_setting_restored(translation_ui):
    app, backend, window = translation_ui
    backend.setPreserveAssFormatting(True)
    backend.stage("text", "Быстрое сохранение")
    assert backend.flush()
    assert backend.editor.document.cues[0].translation == r"{\i1}Быстрое сохранение{\i0}"
    backend.settings.sync()
    restored = Backend()
    try:
        assert restored.preserveAssFormatting
    finally:
        restored.shutdown()
