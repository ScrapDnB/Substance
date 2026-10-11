"""Build the installed PyInstaller version's bootloader with the current SDK.

The SDK opts AppKit into the new design; deployment stays at macOS 15. This
does not patch Mach-O metadata or modify the installed PyInstaller package.
"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
from urllib.request import urlopen


def prepare_bootloader(root):
    import PyInstaller
    from macholib.MachO import MachO
    sdk = subprocess.check_output(['xcrun', '--show-sdk-version'], text=True).strip()
    if int(sdk.split('.')[0]) < 26:
        raise RuntimeError('Liquid Glass packaging requires Xcode with macOS SDK 26 or newer')
    destination = root / 'build/native-bootloader'
    metadata = destination / 'build.json'
    expected = {'pyinstaller': PyInstaller.__version__, 'sdk': sdk, 'deploymentTarget': '15.0'}
    if not metadata.exists() or json.loads(metadata.read_text()) != expected:
        source = root / f'build/bootloader-source/pyinstaller-{PyInstaller.__version__}'
        if not source.exists():
            # Fetch precisely the source matching the runtime package, with PyPI's
            # SHA-256; no dependency installation or system Python modification.
            with urlopen(f'https://pypi.org/pypi/pyinstaller/{PyInstaller.__version__}/json', timeout=60) as response:
                release = json.load(response)
            distribution = next(entry for entry in release['urls'] if entry['packagetype'] == 'sdist')
            archive_path = source.parent / distribution['filename']
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            with urlopen(distribution['url'], timeout=60) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != distribution['digests']['sha256']:
                raise RuntimeError('PyInstaller source checksum mismatch')
            archive_path.write_bytes(data)
            with tarfile.open(archive_path) as archive:
                archive.extractall(source.parent, filter='data')
        environment = os.environ | {'MACOSX_DEPLOYMENT_TARGET': '15.0'}
        # Honor the SDK selected by xcrun, without allowing an inherited SDKROOT
        # to silently build the executable against an older SDK.
        environment['SDKROOT'] = subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip()
        subprocess.run([sys.executable, 'waf', 'all', '--no-universal2'], cwd=source / 'bootloader',
                       env=environment, check=True)
        destination.mkdir(parents=True, exist_ok=True)
        for name in ('run', 'runw', 'run_d', 'runw_d'):
            shutil.copy2(source / 'PyInstaller/bootloader/Darwin-64bit' / name, destination / name)
        metadata.write_text(json.dumps(expected, indent=2))
    # Check actual link commands; do not trust only the recorded SDK version.
    for name in ('run', 'runw', 'run_d', 'runw_d'):
        for header in MachO(str(destination / name)).headers:
            commands = [command for load, command, _ in header.commands if load.cmd == 0x32]
            if not commands or any(command.minos > (15 << 16) or command.sdk < (26 << 16) for command in commands):
                raise RuntimeError(f'{name}: bootloader SDK/deployment target does not match Liquid Glass requirements')
    print(f'Native bootloader uses SDK {sdk}; deployment target macOS 15', flush=True)
    return destination


if __name__ == '__main__':
    prepare_bootloader(Path(__file__).resolve().parents[1])
