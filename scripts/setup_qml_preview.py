"""Install the preview runtime separately from Substance's release dependencies."""
from pathlib import Path
import platform
import subprocess
import sys
import tomllib

ROOT = Path(__file__).resolve().parents[1]


def main():
    if sys.platform == 'darwin' and tuple(map(int, platform.mac_ver()[0].split('.')[:1])) < (26,):
        raise SystemExit('The tested PySide6 6.12.0 macOS bindings require macOS 26+. Ordinary Substance remains on Qt 6.10.2.')
    environment = ROOT / '.venv-qt612'
    python = environment / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    if not python.is_file():
        subprocess.run([sys.executable, '-m', 'venv', str(environment)], check=True)
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    requirements = []
    for requirement in project['dependencies']:
        if requirement.startswith('PySide6=='):
            requirement = 'PySide6==6.12.0'
        elif requirement.startswith('dubbing-online-client=='):
            requirement = str(ROOT / 'vendor/dubbing-online-client')
        requirements.append(requirement)
    requirements.append('pytest>=8,<10')
    subprocess.run([str(python), '-m', 'pip', 'install', *requirements], check=True)
    print('Preview environment ready. Open QML Preview.command on macOS.')


if __name__ == '__main__':
    main()
