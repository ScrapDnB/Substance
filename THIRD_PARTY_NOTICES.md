# Third-party components

Substance uses unmodified third-party runtimes and libraries. Their licenses apply to their respective components; this file does not assign a license to Substance's own code.

| Component | Upstream | License reported by the installed distribution |
|---|---|---|
| Python | https://www.python.org/ | PSF license and incorporated notices |
| PySide6 / Shiboken / Qt | https://www.qt.io/qt-for-python | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only; Qt modules have their own notices |
| NumPy | https://numpy.org/ | BSD-3-Clause and bundled component notices |
| whisper.cpp / ggml | https://github.com/ggml-org/whisper.cpp | MIT; pinned source archive and license are carried with the bundled CLI |
| Whisper model weights (optional download) | https://huggingface.co/ggerganov/whisper.cpp | MIT; models are downloaded separately and verified against pinned SHA-256 checksums |
| Silero VAD v6.2 model | https://github.com/snakers4/silero-vad | MIT; converted ggml weights from https://huggingface.co/ggml-org/whisper-vad are bundled and verified against pinned SHA-256 |
| PyObjC (macOS) | https://pyobjc.readthedocs.io/ | MIT |
| imageio-ffmpeg wrapper | https://github.com/imageio/imageio-ffmpeg | BSD-2-Clause |
| FFmpeg / ffprobe | https://ffmpeg.org/ | Depends on the binary configuration; the bundled conda-forge ffprobe reports GPL version 3 or later |
| libass | https://github.com/libass/libass | ISC |
| pyspellchecker | https://github.com/barrust/pyspellchecker | MIT; dictionary notices are provided by upstream |
| PyInstaller bootloader | https://pyinstaller.org/ | GPL with the bootloader exception |
| Chakra Petch Bold | https://github.com/google/fonts/tree/main/ofl/chakrapetch | SIL Open Font License 1.1; bundled with `resources/fonts/ChakraPetch-OFL.txt` |

The FFmpeg decoder supplied by Qt reports LGPL version 2.1 or later. Audio analysis and subtitle extraction run FFmpeg as a separate process; the package carries the imageio-ffmpeg executable as a fallback. ffprobe is also a separate executable. Shared library dependencies are collected by PyInstaller. Native AppKit functionality is supplied by macOS.

License texts from the locally installed dependencies are collected in `substance/resources/licenses` when building. Build provenance and binary configuration are recorded there as well. Upstream source code and additional component notices are available from the links above and the installed distribution metadata. Developer signing, notarization and public release packaging are separate from this local alpha build.

The macOS build uses conda-forge media libraries to preserve the macOS 15 deployment target. Their package metadata, origin URLs and notices are included in `CONDA-PROVENANCE.json` and `licenses/conda`. Micromamba is a build tool and is not shipped with the application.
