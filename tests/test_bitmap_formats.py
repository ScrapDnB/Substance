import base64
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest
from PIL import Image

from substance.bitmap_subtitles import BitmapJob, bitmap_identity


def pgs_file(path):
    def segment(time,kind,data):
        return b'PG'+struct.pack('>IIBH',time*90000,0,kind,len(data))+data
    pcs=struct.pack('>HHBHBBBB',1280,720,0x10,0,0x80,0,0,1)+struct.pack('>HBBHH',0,0,0,400,600)
    window=bytes([1,0])+struct.pack('>HHHH',400,600,8,4)
    palette=bytes([0,0,0,16,128,128,0,1,235,128,128,255])
    image=bytes([0,2,1,1,1,1,0,2,0,0])*4
    obj=struct.pack('>HB',0,0)+bytes([0xc0])+(len(image)+4).to_bytes(3,'big')+struct.pack('>HH',8,4)+image
    clear=struct.pack('>HHBHBBBB',1280,720,0x10,1,0,0,0,0)
    path.write_bytes(b''.join([segment(1,0x16,pcs),segment(1,0x17,window),segment(1,0x14,palette),
        segment(1,0x15,obj),segment(1,0x80,b''),segment(3,0x16,clear),segment(3,0x80,b'')]))
    return path


def test_real_pgs_decode_is_isolated_and_preserves_original_times(tmp_path):
    if importlib.util.find_spec('av') is None:
        pytest.skip('Install the PyAV runtime dependency')
    path=pgs_file(tmp_path/'fixture.sup')
    helper=Path(__file__).resolve().parents[1]/'substance/bitmap_decode.py'
    result=subprocess.run([sys.executable,str(helper),str(path),'0'],capture_output=True,text=True,timeout=20)
    assert result.returncode==0,result.stderr
    rows=[json.loads(row) for row in result.stdout.splitlines()]
    assert len(rows)==1 and (rows[0]['start'],rows[0]['end'])==(1000,3000)
    image=Image.open(io.BytesIO(base64.b64decode(rows[0]['image'])))
    assert image.getpixel((14,12))==(255,255,255)
    assert image.getpixel((12,12))==(16,16,16)
    assert 'cv2' not in result.stderr and 'AVFFrameReceiver' not in result.stderr


def test_decoded_bitmaps_enter_ocr_with_their_exact_intervals(tmp_path):
    if importlib.util.find_spec('av') is None:
        pytest.skip('Install the PyAV runtime dependency')
    job=BitmapJob(str(pgs_file(tmp_path/'fixture.sup')),0,{}, {})
    job.recognize=lambda image: ('Fixture',.99)
    results=[];job.signals.result.connect(results.append);job.execute()
    row=results[0]['rows'][0]
    assert (row['start'],row['end'],row['text'],row['checked'])==(1000,3000,'Fixture',True)


def test_vobsub_identity_includes_the_companion_binary(tmp_path):
    idx=tmp_path/'fixture.idx';idx.write_text('index')
    sub=tmp_path/'fixture.sub';sub.write_bytes(b'first')
    previous=bitmap_identity(idx)
    sub.write_bytes(b'second')
    assert previous != bitmap_identity(idx)


def test_worker_preserves_redirected_output_without_python_stdout(tmp_path):
    path = pgs_file(tmp_path / 'fixture.sup')
    result = subprocess.run(
        [sys.executable, '-c',
         'import sys; from substance.bitmap_decode import main; sys.stdout = None; raise SystemExit(main(sys.argv[1:]))',
         str(path), '0'], capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    assert len(rows) == 1
    assert (rows[0]['start'], rows[0]['end']) == (1000, 3000)
