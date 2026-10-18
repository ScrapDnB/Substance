"""Carry the installed upstream notices and binary build provenance into the app."""
from importlib.metadata import distribution, PackageNotFoundError
from pathlib import Path
import shutil
import subprocess
import sys
import os
import json

root = Path(__file__).resolve().parents[1]
target = root / 'substance/resources/licenses'
target.mkdir(parents=True, exist_ok=True)
shutil.copyfile(root / 'THIRD_PARTY_NOTICES.md', target / 'THIRD_PARTY_NOTICES.md')
provenance = ['Built with Python ' + sys.version, 'Platform: ' + sys.platform]
python_license = Path(sys.base_prefix) / f'lib/python{sys.version_info.major}.{sys.version_info.minor}/LICENSE.txt'
if python_license.is_file():
    shutil.copyfile(python_license, target / 'Python-LICENSE.txt')
for name in ('dubbing-online-client', 'PySide6', 'PySide6-Essentials', 'PySide6-Addons', 'shiboken6', 'numpy', 'opencv-python-headless', 'onnxruntime', 'pillow', 'filelock', 'protobuf', 'flatbuffers', 'imageio-ffmpeg', 'pyspellchecker', 'pyinstaller', 'pyobjc-core', 'pyobjc-framework-Cocoa', 'pyobjc-framework-Vision', 'pyobjc-framework-Quartz', 'pyobjc-framework-CoreML', 'keyring', 'certifi', 'paramiko', 'cryptography', 'bcrypt', 'pynacl', 'cffi', 'pycparser', 'invoke', 'jaraco.classes', 'jaraco.functools', 'jaraco.context', 'more-itertools', 'backports.tarfile'):
    try:
        package = distribution(name)
    except PackageNotFoundError:
        continue
    provenance.append(f'{name}: {package.version}')
    (target / (name + '-METADATA.txt')).write_text(package.read_text('METADATA') or '', encoding='utf-8')
    for entry in package.files or []:
        if 'dist-info' not in str(entry) or not any(s in entry.name.upper() for s in ('LICENSE', 'COPYING')):
            continue
        source = Path(package.locate_file(entry))
        if source.is_file():
            filename = name + '-' + str(entry).split('dist-info/', 1)[-1].replace('/', '_')
            shutil.copyfile(source, target / filename)

portable_probe = root / 'build/portable/bin/ffprobe'
probe = os.environ.get('SUBSTANCE_FFPROBE') or (str(portable_probe) if portable_probe.is_file() else shutil.which('ffprobe'))
if probe:
    result = subprocess.run([probe, '-L'], capture_output=True, text=True, timeout=10)
    provenance.append(result.stdout + result.stderr)
    # Homebrew keeps the upstream GNU license texts next to its binaries.
    for source in Path(probe).resolve().parent.parent.glob('COPYING*'):
        shutil.copyfile(source, target / ('FFmpeg-' + source.name))
if sys.platform == 'darwin':
    for prefix in ('/opt/homebrew/Cellar/libass', '/usr/local/Cellar/libass'):
        for source in Path(prefix).glob('*/COPYING'):
            shutil.copyfile(source, target / 'libass-ISC.txt')
    portable = root / 'build/portable'
    if portable.is_dir():
        records = [json.loads(path.read_text()) for path in sorted((portable / 'conda-meta').glob('*.json'))]
        (target / 'CONDA-PROVENANCE.json').write_text(json.dumps(records, indent=2), encoding='utf-8')
        for source in (root / 'build/mamba-root/pkgs').rglob('*'):
            if not source.is_file() or '/info/licenses/' not in str(source):
                continue
            package, filename = str(source).split('/info/licenses/', 1)
            destination = target / 'conda' / Path(package).name / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
try:
    import imageio_ffmpeg
    result = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-L'], capture_output=True, text=True, timeout=10)
    provenance.append('imageio FFmpeg executable:\n' + result.stdout + result.stderr)
except (OSError, RuntimeError, subprocess.TimeoutExpired):
    pass
(target / 'BUILD-PROVENANCE.txt').write_text('\n\n'.join(provenance), encoding='utf-8')
