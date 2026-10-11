from pathlib import Path
import os
import sys
import shutil
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)

class NativeSDKEXE(EXE):
    def _bootloader_file(self, exe, extension=None):
        installed = super()._bootloader_file(exe, extension)
        if sys.platform != 'darwin':
            return installed
        native = root / 'build/native-bootloader' / Path(installed).name
        if not native.is_file():
            raise RuntimeError('Run scripts/build.py to prepare the current-SDK macOS bootloader')
        return str(native)

    def assemble(self):
        if sys.platform != 'darwin':
            return super().assemble()
        from PyInstaller.utils import osx
        original = osx.set_macos_sdk_version
        def preserve_linked_sdk(filename, *version):
            if Path(filename).resolve() == Path(self.name).resolve():
                # PyInstaller normally lowers the executable's SDK to Python's
                # SDK as a workaround for old Tk. This Qt/AppKit app needs the
                # actual SDK used to compile its native bootloader preserved.
                print('Preserving the natively linked SDK for Qt/AppKit Liquid Glass', flush=True)
                return
            return original(filename, *version)
        try:
            osx.set_macos_sdk_version = preserve_linked_sdk
            return super().assemble()
        finally:
            osx.set_macos_sdk_version = original

datas = [(str(root / "substance/qml"), "substance/qml"), (str(root / "substance/resources"), "substance/resources")]
datas += collect_data_files("imageio_ffmpeg") + collect_data_files("spellchecker")
binaries = []
libass = os.environ.get("SUBSTANCE_LIBASS")
if not libass and sys.platform == "darwin":
    libass = next((str(p) for p in (root / 'build/portable/lib/libass.9.dylib', Path('/opt/homebrew/lib/libass.9.dylib'), Path('/usr/local/lib/libass.9.dylib')) if p.is_file()), None)
if libass:
    binaries.append((libass, "."))
portable_probe = root / 'build/portable/bin/ffprobe'
ffprobe = os.environ.get("SUBSTANCE_FFPROBE") or (str(portable_probe) if portable_probe.is_file() else shutil.which("ffprobe"))
if ffprobe:
    binaries.append((ffprobe, "."))
if sys.platform == "win32":
    for entry in list(binaries):
        # MSYS2 libass has several dependent DLLs. Bundle the transitive closure.
        import pefile
        directory = Path(entry[0]).parent
        available = {p.name.lower(): p for p in directory.glob("*.dll")}
        queue, seen = [Path(entry[0])], set()
        while queue:
            path = queue.pop()
            if path.name.lower() in seen:
                continue
            seen.add(path.name.lower())
            pe = pefile.PE(str(path), fast_load=True)
            pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"]])
            for dependency in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []):
                name = dependency.dll.decode().lower()
                if name in available and name not in seen:
                    dll = available[name]
                    binaries.append((str(dll), "."))
                    queue.append(dll)
            pe.close()

a = Analysis([str(root / "run.py")], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=["PySide6.QtSvg", "substance.visuals", "spellchecker"],
    excludes=["tkinter", "_tkinter", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineQuick", "PySide6.QtWebEngineWidgets", "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.Qt3DCore", "PySide6.Qt3DExtras", "PySide6.QtDesigner"],
    noarchive=False)
pyz = PYZ(a.pure)
icon = str(root / "substance/resources" / ("icon.icns" if sys.platform == "darwin" else "icon.ico"))
exe = NativeSDKEXE(pyz, a.scripts, [], exclude_binaries=True, name="Substance", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False, console=False, icon=icon)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="Substance")
if sys.platform == "darwin":
    app = BUNDLE(coll, name="Substance.app", icon=icon, bundle_identifier="dev.scrapdnb.substance",
        info_plist={
            "CFBundleShortVersionString": "0.1.0", "CFBundleVersion": "4", "SubstanceVersion": "0.1.0-alpha.4",
            "NSHighResolutionCapable": True, "LSMinimumSystemVersion": "15.0", "NSHumanReadableCopyright": "Substance · ScrapDnB",
            "CFBundleDocumentTypes": [
                {"CFBundleTypeName": "ASS Subtitle", "CFBundleTypeExtensions": ["ass", "ssa", "srt", "vtt"], "CFBundleTypeRole": "Editor", "LSHandlerRank": "Alternate"},
                {"CFBundleTypeName": "Substance Project", "CFBundleTypeExtensions": ["substance"], "CFBundleTypeRole": "Editor"}
            ]})
