"""Build the pinned, portable whisper.cpp CLI used by local transcription."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request

VERSION = '1.8.3'
SOURCE_SHA256 = '870ba21409cdf66697dc4db15ebdb13bc67037d76c7cc63756c81471d8f1731a'
ROOT = Path(__file__).resolve().parents[1]
VAD_REVISION = '9ffd54a1e1ee413ddf265af9913beaf518d1639b'
VAD_SHA256 = '2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987'
VAD_FILENAME = 'ggml-silero-v6.2.0.bin'


def prepare_vad(output):
    output.mkdir(parents=True, exist_ok=True)
    path = output / VAD_FILENAME
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == VAD_SHA256:
        return path
    url = f'https://huggingface.co/ggml-org/whisper-vad/resolve/{VAD_REVISION}/{VAD_FILENAME}'
    with urllib.request.urlopen(url, timeout=30) as response:
        data = response.read(2 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != VAD_SHA256:
        raise RuntimeError('Silero VAD model checksum mismatch')
    temporary = path.with_suffix('.part')
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return path


def prepare_whisper(root=ROOT):
    work = root / 'build/transcription'
    output = root / 'build/whisper'
    prepare_vad(output)
    executable = output / ('whisper-cli.exe' if os.name == 'nt' else 'whisper-cli')
    stamp = output / 'build.json'
    if executable.is_file() and stamp.is_file() and json.loads(stamp.read_text()).get('source_sha256') == SOURCE_SHA256:
        record = json.loads(stamp.read_text())
        record.update(vad_revision=VAD_REVISION, vad_sha256=VAD_SHA256)
        stamp.write_text(json.dumps(record, indent=2) + '\n')
        return executable
    work.mkdir(parents=True, exist_ok=True)
    archive = work / f'whisper-v{VERSION}.tar.gz'
    if not archive.is_file():
        with urllib.request.urlopen(f'https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/refs/tags/v{VERSION}', timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SOURCE_SHA256:
        raise RuntimeError('whisper.cpp source archive checksum mismatch; remove ' + str(archive))
    source = work / f'whisper.cpp-{VERSION}'
    if not source.is_dir():
        with tarfile.open(archive) as bundle:
            bundle.extractall(work, filter='data')
    build = work / 'cmake'
    configure = ['cmake', '-S', str(source), '-B', str(build), '-DCMAKE_BUILD_TYPE=Release',
                 '-DBUILD_SHARED_LIBS=OFF', '-DWHISPER_BUILD_TESTS=OFF', '-DWHISPER_BUILD_SERVER=OFF',
                 '-DGGML_NATIVE=OFF', '-DGGML_OPENMP=OFF']
    if sys.platform == 'darwin':
        configure += ['-DCMAKE_OSX_DEPLOYMENT_TARGET=15.0', '-DGGML_METAL=ON', '-DGGML_METAL_EMBED_LIBRARY=ON']
    if os.name == 'nt':
        configure += ['-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded$<$<CONFIG:Debug>:Debug>']
    subprocess.run(configure, check=True)
    subprocess.run(['cmake', '--build', str(build), '--config', 'Release', '--target', 'whisper-cli',
                    '--parallel', str(min(8, os.cpu_count() or 2))], check=True)
    output.mkdir(parents=True, exist_ok=True)
    candidates = [build / 'bin' / executable.name, build / 'bin/Release' / executable.name]
    shutil.copy2(next(path for path in candidates if path.is_file()), executable)
    shutil.copy2(source / 'LICENSE', output / 'LICENSE')
    stamp.write_text(json.dumps({'version': VERSION, 'source_sha256': SOURCE_SHA256,
                                'vad_revision': VAD_REVISION, 'vad_sha256': VAD_SHA256}, indent=2) + '\n')
    return executable


if __name__ == '__main__':
    print(prepare_whisper())
