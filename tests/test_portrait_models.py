import hashlib
import io
import threading

import pytest
from filelock import FileLock

from substance import portrait_models as models
from substance.portrait_models import ModelCancelled


@pytest.fixture
def spec(monkeypatch):
    data = b'verified model data'
    spec = models.ModelFile('test.onnx', 'test/repo', 'pinned', 'test.onnx', len(data), hashlib.sha256(data).hexdigest())
    monkeypatch.setitem(models.MODELS, 'test', (spec,))
    return spec, data


def test_verified_file_is_reused_without_network(spec, tmp_path, monkeypatch):
    spec, data = spec
    (tmp_path / spec.name).write_bytes(data)
    monkeypatch.setattr(models.urllib.request, 'urlopen', lambda *a, **kw: pytest.fail('Already installed model was downloaded again'))
    assert models.prepare_models('test', tmp_path, threading.Event(), lambda *a: None)[spec.name] == str(tmp_path / spec.name)


def test_corrupt_download_never_replaces_file_and_cleans_partial(spec, tmp_path, monkeypatch):
    spec, data = spec
    bad = b'x' * len(data)
    monkeypatch.setattr(models.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(bad))
    with pytest.raises(ValueError, match='сумма'):
        models.prepare_models('test', tmp_path, threading.Event(), lambda *a: None)
    assert not (tmp_path / spec.name).exists()
    assert not list(tmp_path.glob('*.partial'))


def test_two_apps_share_one_download(spec, tmp_path, monkeypatch):
    spec, data = spec
    calls, errors = [], []
    def open_model(*a, **kw):
        calls.append(1)
        return io.BytesIO(data)
    monkeypatch.setattr(models.urllib.request, 'urlopen', open_model)
    def app():
        try:
            models.prepare_models('test', tmp_path, threading.Event(), lambda *a: None)
        except Exception as exc:
            errors.append(exc)
    threads = [threading.Thread(target=app) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert not errors and not any(t.is_alive() for t in threads)
    assert len(calls) == 1
    assert (tmp_path / spec.name).read_bytes() == data


def test_cancel_waiting_for_other_app(spec, tmp_path):
    spec, _ = spec
    stop = threading.Event()
    with FileLock(str(tmp_path / spec.name) + '.lock'):
        timer = threading.Timer(.1, stop.set)
        timer.start()
        try:
            with pytest.raises(ModelCancelled):
                models.prepare_models('test', tmp_path, stop, lambda *a: None)
        finally:
            timer.join()


def test_shared_location_does_not_depend_on_app_name(monkeypatch, qt_application, tmp_path):
    monkeypatch.delenv('DUBBING_MODELS_DIR', raising=False)
    original = qt_application.applicationName()
    try:
        qt_application.setApplicationName('Substance')
        first = models.shared_model_directory()
        qt_application.setApplicationName('DubbingManager')
        assert first == models.shared_model_directory()
    finally:
        qt_application.setApplicationName(original)
    monkeypatch.setenv('DUBBING_MODELS_DIR', str(tmp_path))
    assert models.shared_model_directory() == tmp_path / 'portraits-v1'
