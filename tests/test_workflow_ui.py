import os
from copy import deepcopy
from pathlib import Path

import pytest
import shiboken6
from PySide6.QtCore import QObject, QPointF, QUrl, Qt, QMetaObject, Q_ARG, qInstallMessageHandler
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtTest import QTest

from substance.backend import Backend
from substance.document import Cue, Document, parse_srt
from substance import visuals  # noqa: F401


@pytest.fixture
def workflow_ui(qt_application, tmp_path, monkeypatch):
    monkeypatch.setenv('SUBSTANCE_DATA_DIR',str(tmp_path))
    if QQuickStyle.name() != os.environ.get('SUBSTANCE_TEST_STYLE','Fusion'):
        QQuickStyle.setStyle(os.environ.get('SUBSTANCE_TEST_STYLE','Fusion'))
    b=Backend()
    b._set_document(parse_srt('1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nWorld\n'),'')
    messages=[]
    previous=qInstallMessageHandler(lambda kind,context,message: messages.append(message))
    engine=QQmlApplicationEngine()
    engine.rootContext().setContextProperty('backend',b)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1]/'substance/qml/Main.qml')))
    assert engine.rootObjects(),messages
    window=engine.rootObjects()[0]
    QTest.qWait(80)
    yield b,window,messages
    # Finish Fluent's close animations before deleting their QML context.
    QMetaObject.invokeMethod(window, 'closeAuxiliaryWindows')
    window.hide()
    QTest.qWait(300)
    b.shutdown();shiboken6.delete(window);shiboken6.delete(engine)
    qInstallMessageHandler(previous)


def test_native_menu_routes_tools_to_tasks(workflow_ui):
    b,w,messages=workflow_ui
    for name in ['compareFilesMenuItem','batchFilesMenuItem','pasteFieldsMenuItem','timingProcessMenuItem',
                 'scriptTimingMenuItem','qualityMenu','mediaMenu','bitmapSubtitlesMenuItem','frameIndexMenuItem']:
        assert w.findChild(QObject,name) is not None,name
    assert w.findChild(QObject,'qualityMenu').property('title') == 'Проверка'
    assert w.findChild(QObject,'mediaMenu').property('title') == 'Медиа'
    if os.environ.get('QT_QPA_PLATFORM') == 'cocoa':
        import AppKit
        menu = AppKit.NSApplication.sharedApplication().mainMenu()
        titles = [item.title() for item in menu.itemArray()]
        for title in ('Файл','Правка','Реплики','Тайминг','Проверка','Медиа','Проект'):
            assert title in titles,titles


@pytest.mark.parametrize('kind,name,apply_name',[
    ('compare','transferDialog','transferApply'),('retime','timingProcessDialog','timingProcessApply'),
    ('forced','scriptTimingDialog','scriptApply'),('batch','batchDialog','batchRun'),
    ('bitmap','bitmapSubtitleDialog','bitmapImport'),('frames','frameIndexDialog','buildFrameIndex'),
])
def test_workflow_windows_fit_and_have_no_runtime_errors(workflow_ui,kind,name,apply_name,tmp_path):
    b,w,messages=workflow_ui
    if kind=='compare':
        b.transfer.open('compare')
        p=tmp_path/'reference.srt';p.write_text('1\n00:00:01,100 --> 00:00:02,100\nHello there\n')
        b.transfer.loadReference(str(p))
    elif kind in ('retime','forced'): b.tools.open(kind)
    elif kind=='batch': b.batch_files.open()
    elif kind=='bitmap': b.bitmap_subtitles.requested.emit()
    else: b.frames.open()
    dialog=w.findChild(QObject,name)
    assert dialog and dialog.property('visible')
    dialog.resize(max(820,dialog.minimumWidth()),max(700,dialog.minimumHeight()))
    QTest.qWait(100)
    apply=dialog.findChild(QObject,apply_name)
    point=apply.mapToScene(QPointF())
    assert point.x()>=0 and point.y()>=0
    assert point.x()+apply.width() <= dialog.width()
    assert point.y()+apply.height() <= dialog.height()
    if kind == 'compare':
        choose=dialog.findChild(QObject,'transferChooseFile')
        assert choose.mapToScene(QPointF()).x()+choose.width() <= dialog.width()
    errors=[m for m in messages if any(s in m for s in ['ReferenceError','TypeError','Cannot assign','is not a function','Binding loop'])]
    assert not errors,errors
    folder=os.environ.get('SUBSTANCE_WORKFLOW_SCREENSHOTS')
    if folder:
        Path(folder).mkdir(parents=True,exist_ok=True)
        dialog.grabWindow().save(str(Path(folder)/(kind+'.png')))
    dialog.close()


def test_reopening_an_active_timing_tool_keeps_the_job(workflow_ui):
    b,w,_=workflow_ui
    b.tools.open('retime')
    class Job:
        cancelled=False
        def cancel(self): self.cancelled=True
    job=Job();b.tools._task=job
    b.tools.open('retime')
    assert not job.cancelled
    b.tools._task=None


def test_compare_arrow_navigation_and_space_keep_filtered_selection_and_scroll(workflow_ui):
    b,w,messages=workflow_ui
    source=Document()
    for i in range(40):
        cue=Cue(start=i*2000,end=i*2000+1000,text=f'Line {i+1}',original=f'Line {i+1}')
        source.register_source(cue)
        source.cues.append(cue)
    b._set_document(source,'')
    reference=deepcopy(source)
    for i,cue in enumerate(reference.cues):
        if i%2:
            cue.text += ' changed'
    # A connected player must not steal Space from the comparison list.
    b.media_controller.path='keyboard-test-media'
    b.media_controller.changed.emit()
    b.transfer.open('compare')
    b.transfer._load(reference,'Keyboard fixture')
    dialog=w.findChild(QObject,'transferDialog')
    dialog.resize(820,700)
    listing=dialog.findChild(QObject,'transferList')
    QTest.qWait(60)
    assert listing.property('activeFocus')
    assert b.transfer.previewIndex==0
    assert b.transfer.preview['left']['number']=='2'
    assert listing.property('currentIndex')==0
    QTest.keyClick(dialog,Qt.Key_Up)
    QTest.keyClick(dialog,Qt.Key_Space)
    QTest.qWait(20)
    assert b.transfer.rows[0]['checked'], (b.transfer.previewIndex, listing.property('activeFocus'),
                                         dialog.property('active'), dialog.activeFocusItem(), messages)
    assert b.transfer.previewIndex==0
    assert listing.property('activeFocus')
    QTest.keyClick(dialog,Qt.Key_Down)
    assert b.transfer.preview['left']['number']=='4'
    QTest.keyClick(dialog,Qt.Key_Space)
    QTest.keyClick(dialog,Qt.Key_Space)
    QTest.qWait(20)
    assert b.transfer.rows[0]['checked'] and not b.transfer.rows[1]['checked']
    assert listing.property('currentIndex')==1
    for _ in range(30):
        QTest.keyClick(dialog,Qt.Key_Down)
    QTest.qWait(40)
    assert b.transfer.previewIndex==len(b.transfer.rows)-1
    assert listing.property('currentIndex')==19
    assert listing.property('contentY')>0
    assert b.editor.document==source  # Browsing/marking never applies edits.
    b.transfer.setField('differences',False)
    QTest.qWait(20)
    assert listing.property('currentIndex')==39
    QTest.keyClick(dialog,Qt.Key_Up)
    assert b.transfer.preview['left']['number']=='39'
    b.transfer.setField('differences',True)
    QTest.qWait(20)
    assert listing.property('currentIndex')==0
    assert b.transfer.preview['left']['number']=='2'
    kind=dialog.findChild(QObject,'transferDifferenceKind')
    kind.setProperty('currentIndex',2)  # Time-only: this fixture has no such differences.
    QMetaObject.invokeMethod(kind,'activated',Qt.DirectConnection,Q_ARG(int,2))
    QTest.qWait(30)
    assert b.transfer.differenceFilter=='time'
    assert not b.transfer.rows and listing.property('currentIndex')==-1
    kind.setProperty('currentIndex',1)
    QMetaObject.invokeMethod(kind,'activated',Qt.DirectConnection,Q_ARG(int,1))
    QTest.qWait(30)
    assert b.transfer.differenceFilter=='text' and listing.property('activeFocus')
    QTest.keyClick(dialog,Qt.Key_Down)
    assert b.transfer.preview['left']['number']=='4'
    dialog.close()


def test_compare_keyboard_is_safe_with_no_differences(workflow_ui):
    b,w,_=workflow_ui
    b.transfer.open('compare')
    b.transfer._load(deepcopy(b.editor.document),'Identical')
    dialog=w.findChild(QObject,'transferDialog')
    QTest.qWait(40)
    for key in (Qt.Key_Down,Qt.Key_Up,Qt.Key_Space):
        QTest.keyClick(dialog,key)
    assert b.transfer.previewIndex==-1
    assert b.transfer.preview=={}
    assert b.transfer.chosenCount==0
    dialog.close()
