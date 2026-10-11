"""Background text operations and embedded subtitle extraction."""
import re
import subprocess
import threading

from PySide6.QtCore import QObject, QRunnable, Signal
from .document import plain_text, parse_ass
from .media import ffmpeg_executable, process_options


class TaskSignals(QObject):
    completed = Signal(object)
    failed = Signal(str)


class SpellingTask(QRunnable):
    def __init__(self, lines, language, ignored):
        super().__init__()
        self.lines, self.language, self.ignored = lines, language, ignored
        self.signals = TaskSignals()
        self.cancelled = threading.Event()

    def cancel(self):
        self.cancelled.set()

    def run(self):
        try:
            from spellchecker import SpellChecker
            checker = SpellChecker(language=self.language, distance=1)
            checker.word_frequency.load_words(self.ignored)
            results = []
            suggestions = {}
            for index, text in self.lines:
                if self.cancelled.is_set():
                    return
                words = re.findall(r"[^\W\d_]+(?:[-'][^\W\d_]+)*", plain_text(text), re.UNICODE)
                unknown = checker.unknown(w.lower() for w in words if 1 < len(w) < 35)
                for word in dict.fromkeys(words):
                    if word.lower() not in unknown:
                        continue
                    if word.lower() not in suggestions:
                        candidates = checker.candidates(word.lower()) or set()
                        suggestions[word.lower()] = sorted(candidates, key=lambda w: (-checker.word_frequency[w], w))[:5]
                    results.append({"index": index, "number": index + 1, "word": word, "suggestions": suggestions[word.lower()]})
                    if len(results) >= 500:
                        break
                if len(results) >= 500:
                    break
            self.signals.completed.emit(results)
        except Exception as exc:
            self.signals.failed.emit(str(exc))


class ExtractTask(QRunnable):
    def __init__(self, path, track):
        super().__init__()
        self.path, self.track = path, track
        self.signals = TaskSignals()
        self.cancelled = threading.Event()
        self.process = None

    def cancel(self):
        self.cancelled.set()
        if self.process and self.process.poll() is None:
            try:
                self.process.terminate()
            except OSError:
                pass

    def run(self):
        try:
            if self.cancelled.is_set():
                return
            self.process = subprocess.Popen([ffmpeg_executable(), "-nostdin", "-v", "error", "-i", self.path, "-map", f"0:s:{self.track}", "-c:s", "ass", "-f", "ass", "pipe:1"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, **process_options())
            if self.cancelled.is_set():
                return
            output, error = self.process.communicate(timeout=60)
            if self.cancelled.is_set():
                return
            if self.process.returncode:
                raise ValueError(error.decode(errors="replace")[:2000] or "Не удалось извлечь дорожку")
            doc = parse_ass(output.decode("utf-8-sig"))
            doc.metadata.update(source_path=self.path, source_format="embedded", subtitle_track=self.track)
            doc.media["path"] = self.path
            self.signals.completed.emit(doc)
        except Exception as exc:
            if not self.cancelled.is_set():
                self.signals.failed.emit(str(exc))
        finally:
            if self.process and self.process.poll() is None:
                self.process.kill()
                self.process.wait()
