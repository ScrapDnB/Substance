"""Build on the target OS. The resulting app carries its Python/Qt runtime."""
from pathlib import Path
import os
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
os.chdir(root)
os.environ.setdefault("PYINSTALLER_CONFIG_DIR", str(root / "build/pyinstaller-cache"))
output_dir = Path(os.environ.get("SUBSTANCE_BUILD_DIST", str(root / "dist"))).resolve()
if sys.platform == 'darwin':
    from build_macos_bootloader import prepare_bootloader
    prepare_bootloader(root)
subprocess.run([sys.executable, str(root / "scripts/collect_licenses.py")], check=True)
subprocess.run([sys.executable, str(root / "scripts/create_icons.py")], check=True)
subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--distpath", str(output_dir), str(root / "substance.spec")], check=True)
if sys.platform == 'darwin':
    from verify_macos_minimum import executable_sdk, verify_app
    report = verify_app(output_dir / 'Substance.app')
    sdk = executable_sdk(output_dir / 'Substance.app')
    if sdk < (26, 0, 0):
        raise RuntimeError('Packaged executable must be linked with SDK 26+ to enable AppKit Liquid Glass')
    report['executableSDK'] = '.'.join(map(str, sdk))
    import json
    output = root / 'build/qa/macos-minimum.json'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(f"Verified {report['filesChecked']} bundled binaries for macOS {report['declaredMinimum']}")
