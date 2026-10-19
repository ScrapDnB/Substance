"""Launch the frozen app without source or build-time media library overrides."""
from pathlib import Path
import json
import os
import runpy
import subprocess
import sys
import tempfile


def main():
    root = Path(__file__).resolve().parents[1]
    dist = Path(os.environ.get("SUBSTANCE_BUILD_DIST", root / "dist")).resolve()
    executable = (dist / "Substance.app/Contents/MacOS/Substance" if sys.platform == "darwin"
                  else dist / "Substance/Substance.exe")
    if not executable.is_file():
        raise RuntimeError(f"Packaged executable not found: {executable}")
    qa = root / "build/qa"
    qa.mkdir(parents=True, exist_ok=True)
    diagnostics = qa / "ci-package.json"
    diagnostics.unlink(missing_ok=True)
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith(("SUBSTANCE_", "PYTHON", "QT_", "QML"))}
    environment["QT_QPA_PLATFORM"] = "cocoa" if sys.platform == "darwin" else "windows"
    environment["PATH"] = os.pathsep.join(
        entry for entry in environment.get("PATH", "").split(os.pathsep)
        if "msys" not in entry.lower() and "build/portable" not in entry.replace("\\", "/"))
    with tempfile.TemporaryDirectory(prefix="substance-package-") as temporary:
        environment["SUBSTANCE_DATA_DIR"] = temporary
        with (qa / "ci-package.log").open("w", encoding="utf-8") as log:
            subprocess.run(
                [str(executable), "--smoke-test", "--diagnostics", str(diagnostics)],
                cwd=temporary, env=environment, stdout=log, stderr=subprocess.STDOUT,
                timeout=60, check=True,
            )
        report = json.loads(diagnostics.read_text(encoding="utf-8"))
        expected_version = runpy.run_path(str(root / "substance/__init__.py"))["__version__"]
        if report.get("version") != expected_version:
            raise RuntimeError(f"Unexpected packaged version: {report.get('version')}; expected {expected_version}")
        from PySide6.QtCore import qVersion
        if report.get('qtVersion') != qVersion() or report.get('qmlPreview') is not False:
            raise RuntimeError(f'Unexpected Qt runtime or preview mode in the release package: {report}')
        preview = subprocess.run([str(executable), '--qml-preview'], cwd=temporary, env=environment,
                                 capture_output=True, text=True, timeout=30)
        if preview.returncode != 2 or (sys.platform != 'win32' and 'only when running from source' not in preview.stderr):
            raise RuntimeError('The release package did not reject the development-only QML preview mode')
        # Exercise PyAV and its native libraries in the frozen worker, including
        # redirected output from the Windows executable without a console.
        bitmap = subprocess.run(
            [str(executable), '--decode-bitmaps', str(root / 'tests/fixtures/bitmap.sup'), '0'],
            cwd=temporary, env=environment, capture_output=True, timeout=30, check=True)
        rows = [json.loads(line) for line in bitmap.stdout.splitlines()]
        if len(rows) != 1 or (rows[0]['start'], rows[0]['end']) != (1000, 3000) or not rows[0]['image']:
            raise RuntimeError('Packaged PGS decoder did not preserve the subtitle image and interval')
        expected_style = "macOS" if sys.platform == "darwin" else "FluentWinUI3"
        if report["style"] != expected_style or report["platform"] != sys.platform:
            raise RuntimeError(f"Unexpected packaged platform or style: {report}")
        for key in ("ffmpeg", "ffprobe", "libass", "whisper", "speechVAD"):
            path = Path(report.get(key) or "")
            if not path.is_file() or not path.resolve().is_relative_to(dist):
                raise RuntimeError(f"Missing bundled {key}: {report.get(key)}")
        for key in ("ffmpeg", "ffprobe"):
            result = subprocess.run([report[key], "-version"], cwd=temporary, env=environment,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            (qa / f"ci-package-{key}.log").write_bytes(result.stdout + result.stderr)
            if result.returncode:
                raise RuntimeError(f"Bundled {key} failed ({result.returncode}): "
                                   + result.stderr.decode('utf-8', errors='replace'))
        subprocess.run([report['whisper'], '--help'], cwd=temporary, env=environment,
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=30)
    print("Packaged QML, platform style, FFmpeg and ffprobe verified", flush=True)


if __name__ == "__main__":
    main()
