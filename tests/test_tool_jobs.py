from copy import deepcopy
import subprocess

from PySide6.QtCore import QEventLoop, QTimer

from substance.backend import Backend
from substance.document import Document, Cue, save_document, load_document
from substance.media import ffmpeg_executable
from substance.tool_jobs import SceneJob, video_identity


def video(path):
    subprocess.run([ffmpeg_executable(), '-v', 'error', '-y', '-f', 'lavfi', '-i',
                    'color=black:s=160x90:r=25:d=1', '-f', 'lavfi', '-i',
                    'color=white:s=160x90:r=25:d=1', '-filter_complex',
                    '[0:v][1:v]concat=n=2:v=1:a=0', '-c:v', 'mpeg4', str(path)], check=True)


def wait():
    loop = QEventLoop()
    QTimer.singleShot(20, loop.quit)
    loop.exec()


def test_scene_detection_real_ffmpeg_cache_and_cancel(qt_application, tmp_path):
    path = tmp_path / 'cuts.mp4'
    video(path)
    result = []
    task = SceneJob(str(path), 10, 2000, tmp_path / 'cache')
    task.signals.result.connect(result.append)
    task.execute()
    assert result[0]['times'] == [1000]
    assert result[0]['identity'] == video_identity(path)
    cached = SceneJob(str(path), 10, 2000, tmp_path / 'cache')
    cached.signals.result.connect(result.append)
    cached.execute()
    assert cached.process is None and result[0] == result[1]
    cancelled = SceneJob(str(path), 10, 2000, tmp_path / 'cache')
    cancelled.signals.result.connect(result.append)
    cancelled.cancel()
    cancelled.run()
    assert len(result) == 2


def test_scene_apply_undo_restore_and_track_change_invalidation(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR', str(tmp_path / 'data'))
    path = tmp_path / 'cuts.mp4'
    video(path)
    b = Backend()
    try:
        doc = Document(media={'path': str(path)})
        cue = Cue(start=0, end=2000, text='Test', original='Test')
        doc.register_source(cue)
        doc.cues = [cue]
        b._set_document(doc, '')
        b.media_controller.open(str(path))
        for _ in range(100):
            if b.media.hasVideo:
                break
            wait()
        assert b.media.hasVideo
        for _ in range(100):
            if not b.media.busy:
                break
            wait()
        before = deepcopy(b.editor.document)
        b.tools.analyze('scenes', {'threshold': 10})
        for _ in range(200):
            if not b.tools.busy:
                break
            wait()
        assert b.tools.canApply, b.tools.status
        assert b.tools.sceneRows == [{'time': 1000, 'label': '00:00:01.000'}]
        assert b.tools.apply(), b.tools.status
        assert b.media.shot_changes == [1000]
        b.undo()
        assert b.media.shot_changes == []
        assert b.editor.document == before
        b.redo()
        assert b.media.shot_changes == [1000]
        b.tools.toggleScene(1500)
        assert b.media.shot_changes == [1000, 1500]
        project = tmp_path / 'markers.substance'
        save_document(b.editor.document, project)
        saved = load_document(project)
        assert saved.media['shot_changes']['times'] == [1000, 1500]
        b.undo()
        assert b.media.shot_changes == [1000]
        # A cached marker set from this video must not leak into another file.
        other = tmp_path / 'different.mp4'
        other.write_bytes(path.read_bytes() + b'changed')
        b.media_controller.open(str(other))
        assert not b.media.shot_changes
    finally:
        b.shutdown()
