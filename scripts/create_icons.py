from pathlib import Path
import os
import subprocess
import sys
import struct

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtCore import Qt

root = Path(__file__).resolve().parents[1]
app = QApplication([])
renderer = QSvgRenderer(str(root / "substance/resources/icon.svg"))
directory = root / "build/icons/Substance.iconset"
directory.mkdir(parents=True, exist_ok=True)
for size in (16, 32, 128, 256, 512):
    for scale in (1, 2):
        image = QImage(size * scale, size * scale, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        renderer.render(painter)
        painter.end()
        image.save(str(directory / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"))
if sys.platform == "darwin":
    # Write PNG-backed ICNS chunks directly; works in headless CI as well.
    types = [("icp4", 16, 1), ("ic11", 16, 2), ("icp5", 32, 1), ("ic12", 32, 2), ("ic07", 128, 1), ("ic13", 128, 2), ("ic08", 256, 1), ("ic14", 256, 2), ("ic09", 512, 1), ("ic10", 512, 2)]
    chunks = []
    for kind, size, scale in types:
        data = (directory / f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png").read_bytes()
        chunks.append(kind.encode() + struct.pack(">I", len(data) + 8) + data)
    content = b"".join(chunks)
    (root / "substance/resources/icon.icns").write_bytes(b"icns" + struct.pack(">I", len(content) + 8) + content)
else:
    data = (directory / "icon_256x256.png").read_bytes()
    header = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(data), 22)
    (root / "substance/resources/icon.ico").write_bytes(header + data)
