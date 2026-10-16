"""Online controls follow the document, including disconnected remote work."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from contextlib import contextmanager
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QUrl, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine, QQmlExpression, qmlContext
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from substance.backend import Backend
from substance.document import load_document, save_document
from substance import visuals  # register QML types
from test_online import backend as online_backend, wait

ROOT = Path(__file__).resolve().parents[1]
ONLINE_DIALOGS = ("onlineConflictDialog", "onlineGlossaryDialog", "onlineWorkflowDialog")


@pytest.fixture(scope="module")
def app():
    instance = QApplication.instance() or QApplication([])
    if QQuickStyle.name() != "Fusion":
        QQuickStyle.setStyle("Fusion")
    return instance


@contextmanager
def window_for(backend):
    messages = []
    previous = qInstallMessageHandler(lambda kind, context, message: messages.append(message))
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    try:
        engine.load(QUrl.fromLocalFile(str(ROOT / "substance/qml/Main.qml")))
        assert engine.rootObjects(), messages
        window = engine.rootObjects()[0]
        QTest.qWait(60)

        def js(code):
            expression = QQmlExpression(qmlContext(window), window, code)
            result = expression.evaluate()
            assert not expression.hasError(), expression.error().toString()
            return result[0]

        yield window, js
        errors = [m for m in messages if any(s in m for s in (
            "ReferenceError", "TypeError", "Cannot assign", "Unable to assign", "Binding loop"))]
        assert not errors, errors
    finally:
        if engine.rootObjects():
            shiboken6.delete(engine.rootObjects()[0])
        shiboken6.delete(engine)
        qInstallMessageHandler(previous)


@pytest.mark.parametrize("kind", ["ass", "srt", "substance", "portable"])
def test_local_files_hide_online_controls_even_with_saved_session(app, tmp_path, monkeypatch, kind):
    monkeypatch.setenv("SUBSTANCE_DATA_DIR", str(tmp_path))
    backend = Backend()
    try:
        document = load_document(ROOT / "substance/resources/example.ass")
        if kind == "portable":
            document.extras["dubbing_online_origin"] = {
                "version": 1, "server_url": "https://example.test",
                "project_id": "project", "episode_id": "episode",
                "base_revision": 1, "base_sha256": "a" * 64,
            }
        path = tmp_path / ("local.substance" if kind == "portable" else f"local.{kind}")
        if kind == "srt":
            path.write_text("1\n00:00:00,000 --> 00:00:02,000\nHello\n", encoding="utf-8")
        else:
            save_document(document, path)
        backend._set_document(load_document(path), str(path))
        (backend.data_dir / "online-last.json").write_text("{}", encoding="utf-8")
        assert backend.online.canResume

        with window_for(backend) as (window, js):
            assert not backend.online.active
            assert not window.findChild(QObject, "onlineStatus").property("visible")
            assert not window.findChild(QObject, "onlineStatus").property("enabled")
            assert window.findChild(QObject, "documentStatusBar").property("height") == 30
            assert not any("онлайн" in (item.property("text") or "").lower()
                           for item in window.findChildren(QObject) if isinstance(item.property("text"), str))
            for name in ONLINE_DIALOGS:
                js(f"{name}.open()")
                assert not window.findChild(QObject, name).property("visible")
            if kind in ("substance", "portable"):
                assert backend.addReview("note", "Локальная заметка", "")
                backend.openReviews()
                assert window.findChild(QObject, "reviewsDialog").property("visible")
                assert js("reviewsDialog.title") == "Заметки и предложения правок"
                assert not window.findChild(QObject, "onlineReviewList").property("visible")
                js("reviewsDialog.close()")
                backend.openCharacters("")
                assert window.findChild(QObject, "characterDialog").property("visible")
                js("characterDialog.close()")
                if kind == "portable":
                    assert backend.editor.document.extras["dubbing_online_origin"] == document.extras["dubbing_online_origin"]
    finally:
        backend.shutdown()


def test_remote_controls_survive_network_failure_and_close_on_disconnect(app, online_backend, monkeypatch):
    backend = online_backend
    errors = []
    monkeypatch.setattr(backend, "show_error", errors.append)

    def unavailable(*args, **kwargs):
        raise OSError("Нет соединения с сервером")

    with window_for(backend) as (window, js):
        panel = window.findChild(QObject, "onlineStatus")
        assert panel.property("visible") and panel.property("enabled")
        assert window.findChild(QObject, "documentStatusBar").property("height") == 66
        monkeypatch.setattr(backend.online.repository.client, "request", unavailable)
        backend.online.sync()
        wait(backend)
        assert errors and "Нет соединения" in backend.online.status
        assert backend.online.active and panel.property("visible")
        for name in ONLINE_DIALOGS:
            js(f"{name}.open()")
            wait(backend)
            assert window.findChild(QObject, name).property("visible")
        backend.notify("На сервере · ревизия 1")
        backend.online.disconnect()
        QTest.qWait(30)
        assert not panel.property("visible") and not panel.property("enabled")
        for name in ONLINE_DIALOGS:
            assert not window.findChild(QObject, name).property("visible")
            js(f"{name}.open()")
            assert not window.findChild(QObject, name).property("visible")
        backend.newDocument()
        assert backend.message == ""
        assert window.findChild(QObject, "documentStatusBar").property("height") == 30
