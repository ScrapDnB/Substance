"""Keep one QApplication alive throughout each test process."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Avoid Python-painted render callbacks contending for the GIL in headless tests.
if os.environ["QT_QPA_PLATFORM"] == "offscreen":
    os.environ.setdefault("QSG_RENDER_LOOP", "basic")
# Hosted runners do not provide a reliable hardware video decoder.
os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", ",")

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    # Individual backend fixtures must not destroy and recreate QApplication
    # while queued Qt signals and worker callbacks still refer to its context.
    app = QApplication.instance() or QApplication([])
    yield app
    app.processEvents()
