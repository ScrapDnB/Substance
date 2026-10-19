# Third-party components

Substance uses unmodified third-party runtimes and libraries. Their licenses apply to their respective components; this file does not assign a license to Substance's own code.

| Component | Upstream | License reported by the installed distribution |
|---|---|---|
| Python | https://www.python.org/ | PSF license and incorporated notices |
| PySide6 / Shiboken / Qt | https://www.qt.io/qt-for-python | LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only; Qt modules have their own notices |
| NumPy | https://numpy.org/ | BSD-3-Clause and bundled component notices |
| OpenCV (headless runtime) | https://github.com/opencv/opencv-python | Apache-2.0; wheel includes additional third-party notices |
| ONNX Runtime | https://github.com/microsoft/onnxruntime | MIT and incorporated notices |
| PyAV and its FFmpeg libraries | https://github.com/PyAV-Org/PyAV | BSD-3-Clause; the wheel carries separate FFmpeg and codec notices. Bitmap decoding runs in an isolated helper process. |
| wav2vec2 acoustic alignment weights (optional downloads) | https://huggingface.co/Xenova/wav2vec2-base-960h and https://huggingface.co/onnx-community/wav2vec2-large-xlsr-53-russian-ONNX | Original facebook wav2vec2 and Russian fine-tuned model report Apache-2.0. ONNX weights are pinned to immutable revisions with SHA-256 verification; weights are not bundled. |
| Pillow | https://python-pillow.org/ | MIT-CMU and incorporated notices |
| filelock | https://github.com/tox-dev/filelock | Unlicense |
| YuNet / SFace weights (optional download) | https://huggingface.co/opencv/face_detection_yunet and https://huggingface.co/opencv/face_recognition_sface | MIT / Apache-2.0 respectively; see pinned repositories |
| Anime face detector / CCIP weights (optional download) | https://huggingface.co/deepghs/anime_face_detection and https://huggingface.co/deepghs/ccip_onnx | Model cards declare MIT / OpenRAIL respectively; see pinned model cards and their terms |
| whisper.cpp / ggml | https://github.com/ggml-org/whisper.cpp | MIT; pinned source archive and license are carried with the bundled CLI; local patch streams lossless DTW token data and repairs batch callbacks (`scripts/whisper_tokens.py`) |
| Whisper model weights (optional download) | https://huggingface.co/ggerganov/whisper.cpp | MIT; models are downloaded separately and verified against pinned SHA-256 checksums |
| Silero VAD v6.2 model | https://github.com/snakers4/silero-vad | MIT; converted ggml weights from https://huggingface.co/ggml-org/whisper-vad are bundled and verified against pinned SHA-256 |
| PyObjC (macOS) | https://pyobjc.readthedocs.io/ | MIT |
| Tesseract (optional external installation; not bundled) | https://github.com/tesseract-ocr/tesseract | Apache-2.0; language data have upstream notices |
| imageio-ffmpeg wrapper | https://github.com/imageio/imageio-ffmpeg | BSD-2-Clause |
| FFmpeg / ffprobe | https://ffmpeg.org/ | Depends on the binary configuration; the bundled conda-forge ffprobe reports GPL version 3 or later |
| libass | https://github.com/libass/libass | ISC |
| pyspellchecker | https://github.com/barrust/pyspellchecker | MIT; dictionary notices are provided by upstream |
| Wiktionary / Kaikki dictionary data (optional download; not bundled) | https://kaikki.org/dictionary/rawdata.html and https://www.wiktionary.org/ | Wiktionary content licenses (CC BY-SA / GFDL); source article links accompany definitions. Wiktextract provides the extraction format. |
| PyInstaller bootloader | https://pyinstaller.org/ | GPL with the bootloader exception |
| Chakra Petch Bold | https://github.com/google/fonts/tree/main/ofl/chakrapetch | SIL Open Font License 1.1; bundled with `resources/fonts/ChakraPetch-OFL.txt` |

The FFmpeg decoder supplied by Qt reports LGPL version 2.1 or later. Audio analysis and subtitle extraction run FFmpeg as a separate process; the package carries the imageio-ffmpeg executable as a fallback. ffprobe is also a separate executable. Shared library dependencies are collected by PyInstaller. Native AppKit functionality is supplied by macOS.

License texts from the locally installed dependencies are collected in `substance/resources/licenses` when building. Build provenance and binary configuration are recorded there as well. Upstream source code and additional component notices are available from the links above and the installed distribution metadata. Developer signing, notarization and public release packaging are separate from this local alpha build.

The macOS build uses conda-forge media libraries to preserve the macOS 15 deployment target. Their package metadata, origin URLs and notices are included in `CONDA-PROVENANCE.json` and `licenses/conda`. Micromamba is a build tool and is not shipped with the application.

- SSH-мастер LibreTranslate: Paramiko (LGPL-2.1), cryptography (Apache-2.0 / BSD-3-Clause), bcrypt и PyNaCl (Apache-2.0), cffi (MIT), pycparser (BSD-3-Clause), Invoke (BSD). Лицензии установленных версий собираются в комплект приложения. LibreTranslate запускается отдельно на сервере и распространяется по AGPL-3.0; образ не входит в Substance.
