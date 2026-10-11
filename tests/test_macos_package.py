"""Guard against raising deployment requirements accidentally during packaging."""
from pathlib import Path
import plistlib
import struct
import sys
import pytest

pytestmark = pytest.mark.skipif(sys.platform != 'darwin', reason='Mach-O verification is a macOS build check')


def app_with_binary(tmp_path, minimum, sdk):
    app = tmp_path / 'Test.app'
    content = app / 'Contents'
    content.mkdir(parents=True)
    (content / 'Info.plist').write_bytes(plistlib.dumps({'LSMinimumSystemVersion': '15.0'}))
    header = struct.pack('<IiiIIIII', 0xfeedfacf, 0x100000c, 0, 6, 1, 24, 0, 0)
    command = struct.pack('<IIIIII', 0x32, 24, 1, minimum << 16, sdk << 16, 0)
    (content / 'library.dylib').write_bytes(header + command)
    return app


def test_new_sdk_does_not_raise_minimum_os(tmp_path):
    from scripts.verify_macos_minimum import verify_app
    report = verify_app(app_with_binary(tmp_path, 11, 27))
    assert report['filesChecked'] == 1
    assert report['highestMinimum'] == '11.0.0'
    assert report['incompatible'] == []


def test_newer_runtime_is_rejected_even_with_older_sdk(tmp_path):
    from scripts.verify_macos_minimum import verify_app
    with pytest.raises(RuntimeError, match='library.dylib'):
        verify_app(app_with_binary(tmp_path, 26, 26))


def test_executable_sdk_is_separate_from_runtime_minimum(tmp_path):
    from scripts.verify_macos_minimum import executable_sdk, verify_app
    app = app_with_binary(tmp_path, 15, 27)
    content = app / 'Contents'
    info = plistlib.loads((content / 'Info.plist').read_bytes())
    info['CFBundleExecutable'] = 'Substance'
    (content / 'Info.plist').write_bytes(plistlib.dumps(info))
    (content / 'MacOS').mkdir()
    (content / 'library.dylib').rename(content / 'MacOS/Substance')
    assert executable_sdk(app) == (27, 0, 0)
    assert verify_app(app)['highestMinimum'] == '15.0.0'
