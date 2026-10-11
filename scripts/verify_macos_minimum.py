"""Validate deployment targets of every bundled Mach-O, not just Info.plist."""
from pathlib import Path
import argparse
import json
import plistlib


def version(number):
    return number >> 16, (number >> 8) & 255, number & 255


def minimum_versions(path):
    from macholib.MachO import MachO
    versions = []
    for header in MachO(str(path)).headers:
        for load, command, _data in header.commands:
            if load.cmd == 0x32:  # LC_BUILD_VERSION; sdk is NOT the minimum OS.
                if command.platform == 1:
                    versions.append(version(command.minos))
            elif load.cmd == 0x24:  # LC_VERSION_MIN_MACOSX
                versions.append(version(command.version))
    return versions


def executable_sdk(app):
    """Read the executable's linked SDK separately from its deployment target."""
    from macholib.MachO import MachO
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    path = app / 'Contents/MacOS' / info['CFBundleExecutable']
    versions = []
    for header in MachO(str(path)).headers:
        for load, command, _ in header.commands:
            if load.cmd == 0x32 and command.platform == 1:
                versions.append(version(command.sdk))
            elif load.cmd == 0x24:
                versions.append(version(command.sdk))
    return min(versions, default=(0, 0, 0))


def verify_app(app: Path):
    info = plistlib.loads((app / 'Contents/Info.plist').read_bytes())
    declared = tuple(map(int, info['LSMinimumSystemVersion'].split('.')))
    declared = (declared + (0, 0, 0))[:3]
    files, seen, incompatible = [], set(), []
    magic = {b'\xfe\xed\xfa\xce', b'\xce\xfa\xed\xfe', b'\xfe\xed\xfa\xcf', b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xbe\xba\xfe\xca', b'\xca\xfe\xba\xbf', b'\xbf\xba\xfe\xca'}
    for path in app.rglob('*'):
        if not path.is_file() or path.resolve() in seen:
            continue
        seen.add(path.resolve())
        with path.open('rb') as stream:
            if stream.read(4) not in magic:
                continue
        versions = minimum_versions(path)
        if not versions:
            continue
        required = max(versions)
        item = {'path': str(path.relative_to(app)), 'minimum': '.'.join(map(str, required))}
        files.append(item)
        if required > declared:
            incompatible.append(item)
    report = {'declaredMinimum': '.'.join(map(str, declared)), 'filesChecked': len(files), 'highestMinimum': max((item['minimum'] for item in files), key=lambda value: tuple(map(int, value.split('.'))), default='0.0.0'), 'incompatible': incompatible, 'files': files}
    if incompatible:
        raise RuntimeError('Bundled binaries require a newer macOS than Info.plist: ' + json.dumps(incompatible, ensure_ascii=False))
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('app', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    report = verify_app(args.app)
    if args.report:
        args.report.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Checked {report['filesChecked']} Mach-O files; declared minimum macOS {report['declaredMinimum']}, highest dependency {report['highestMinimum']}")
